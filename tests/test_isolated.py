"""Isolated regression/security tests. Uses only a temporary SQLite database and dummy secrets."""
import base64
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TMP = tempfile.TemporaryDirectory(prefix="responde-ai-tests-")
os.environ["DB_PATH"] = str(Path(TMP.name) / "test.sqlite3")
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-telegram-token-for-tests"
os.environ["ADMIN_KEY"] = "dummy-admin-key-for-tests"
os.environ["ATAJO_KEY"] = "dummy-atajo-key-for-tests"
os.environ["BANDEC_ACCOUNT"] = "9244069990684435"
os.environ["BPA_ACCOUNT"] = "1234567890123456"

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def auth(uid="test-user"):
    main.user(uid)
    return {"Authorization": "Bearer " + main.session_token(uid)}


class TestHardening(unittest.TestCase):
    def test_health(self):
        self.assertEqual(client.get("/health").status_code, 200)

    def test_usage_requires_auth(self):
        self.assertEqual(client.post("/api/usage", json={"user_id":"victim"}).status_code, 401)

    def test_user_id_body_cannot_override_token(self):
        headers = auth("owner-test")
        r = client.post("/api/profile", headers=headers, json={"user_id":"victim"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user_id"], "owner-test")

    def test_free_limit_under_concurrency(self):
        uid = "concurrent-user"
        headers = auth(uid)
        payload = {"user_id":uid,"module":"chat","mode":"coquetear"}
        def run(_):
            return client.post("/api/analyze", headers=headers, json=payload).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(run, range(8)))
        self.assertEqual(statuses.count(200), 3, statuses)
        self.assertEqual(statuses.count(403), 5, statuses)

    def test_phone_prefix_is_normalized(self):
        headers = auth("phone-user")
        r = client.post("/api/payment-phone", headers=headers, json={"phone":"+53 52677163"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["payment_phone"], "52677163")

    def test_phone_invalid_rejected(self):
        self.assertEqual(client.post("/api/payment-phone", headers=auth("phone-bad"), json={"phone":"123"}).status_code, 400)

    def test_ocr_requires_auth(self):
        self.assertEqual(client.post("/ocr", content=b"bad-image").status_code, 401)

    def test_ocr_rejects_invalid_image_safely(self):
        r = client.post("/ocr", headers=auth("ocr-user"), content=b"not an image")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Imagen inválida o dañada")

    def test_ocr_stream_size_limit(self):
        r = client.post("/ocr", headers=auth("ocr-large"), content=b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(r.status_code, 413)

    def test_base64_ocr_size_limit(self):
        oversized = base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode()
        r = client.post("/ocr-base64", json={"image":oversized})
        self.assertEqual(r.status_code, 413)

    def test_diagnostic_requires_secret(self):
        self.assertEqual(client.post("/api/atajo-diagnostico", content=b"x").status_code, 401)
        r = client.post("/api/atajo-diagnostico", headers={"x-atajo-key":os.environ["ATAJO_KEY"]}, content=b"hello")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["bytes_recibidos"], 5)

    def test_bank_shortcut_verifies_one_matching_operation(self):
        uid = "bank-clean"
        headers = auth(uid)
        self.assertEqual(client.post("/api/payment-phone", headers=headers, json={"phone":"52677163"}).status_code, 200)
        p = client.post("/api/payments/pending", headers=headers, json={"user_id":uid,"plan":"weekly","language":"es","payment_method":"BANDEC"})
        self.assertEqual(p.status_code, 200, p.text)
        operation_id = p.json()["operation_id"]
        r = client.post("/api/atajo-pago", headers={"x-atajo-key":os.environ["ATAJO_KEY"]}, json={
            "metodo_pago":"BANDEC", "telefono_origen":"52677163", "cuenta_destino":"9244069990684435",
            "monto_recibido":2500, "transaccion":"TX-UNIQUE-001", "fecha":"2026-10-09"
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("status"), "verified", r.json())
        c = main.db()
        payment = c.execute("SELECT status,transaction_id FROM payment_operations WHERE operation_id=?", (operation_id,)).fetchone()
        premium_until = c.execute("SELECT premium_until FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        c.close()
        self.assertEqual(payment["status"], "verified")
        self.assertEqual(payment["transaction_id"], "TX-UNIQUE-001")
        self.assertTrue(premium_until)


    def test_bpa_shortcut_uses_configured_bpa_destination(self):
        uid = 'bpa-clean'
        headers = auth(uid)
        self.assertEqual(client.post('/api/payment-phone', headers=headers, json={'phone':'52677163'}).status_code, 200)
        pending = client.post('/api/payments/pending', headers=headers, json={
            'user_id': uid, 'plan': 'weekly', 'language': 'es', 'payment_method': 'BPA'
        })
        self.assertEqual(pending.status_code, 200, pending.text)
        result = client.post('/api/atajo-pago', headers={'x-atajo-key': os.environ['ATAJO_KEY']}, json={
            'metodo_pago': 'BPA', 'telefono_origen': '52677163',
            'cuenta_destino': os.environ['BPA_ACCOUNT'], 'monto_recibido': 2500,
            'transaccion': 'BPA-TX-UNIQUE-002', 'fecha': '2026-10-10'
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json().get('status'), 'verified', result.json())
        self.assertTrue(main.premium(uid))

    def test_saldo_movil_shortcut_checks_sms_phone_amount_and_duplicate(self):
        uid = 'saldo-clean'
        headers = auth(uid)
        self.assertEqual(client.post('/api/payment-phone', headers=headers, json={'phone':'52677164'}).status_code, 200)
        pending = client.post('/api/payments/pending', headers=headers, json={
            'user_id': uid, 'plan': 'weekly', 'language': 'es', 'payment_method': 'SALDO_MOVIL'
        })
        self.assertEqual(pending.status_code, 200, pending.text)
        payload = {
            'metodo_pago': 'SALDO_MOVIL', 'telefono_origen': '52677164',
            'monto_recibido': 2500, 'sms': 'El numero 52677164 ha recibido 2500 CUP'
        }
        result = client.post('/api/atajo-pago', headers={'x-atajo-key': os.environ['ATAJO_KEY']}, json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json().get('status'), 'verified', result.json())
        self.assertTrue(main.premium(uid))
        duplicate = client.post('/api/atajo-pago', headers={'x-atajo-key': os.environ['ATAJO_KEY']}, json=payload)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json().get('status'), 'duplicate', duplicate.json())

    def test_saldo_movil_rejects_amount_mismatch(self):
        uid = 'saldo-mismatch'
        headers = auth(uid)
        client.post('/api/payment-phone', headers=headers, json={'phone':'52677165'})
        client.post('/api/payments/pending', headers=headers, json={
            'user_id': uid, 'plan': 'weekly', 'language': 'es', 'payment_method': 'SALDO_MOVIL'
        })
        result = client.post('/api/atajo-pago', headers={'x-atajo-key': os.environ['ATAJO_KEY']}, json={
            'metodo_pago': 'SALDO_MOVIL', 'telefono_origen': '52677165',
            'monto_recibido': 2500, 'sms': 'El numero 52677165 ha recibido 1500 CUP'
        })
        self.assertEqual(result.status_code, 400, result.text)

    def test_duplicate_bank_transaction_does_not_grant_again(self):
        # Replaying the exact same transaction is idempotently rejected as duplicate.
        payload = {"metodo_pago":"BANDEC", "telefono_origen":"52677163", "cuenta_destino":"9244069990684435", "monto_recibido":2500, "transaccion":"TX-UNIQUE-001", "fecha":"2026-10-09"}
        r = client.post("/api/atajo-pago", headers={"x-atajo-key":os.environ["ATAJO_KEY"]}, json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "duplicate")

    def test_static_assets(self):
        for path in ("/", "/app.js", "/style.css", "/admin.html", "/privacy.html", "/terms.html"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestPremiumAndRetries(unittest.TestCase):
    def test_free_user_cannot_use_premium_mode(self):
        r = client.post('/api/analyze', headers=auth('premium-denied'), json={'user_id':'x','module':'chat','mode':'provocativo'})
        self.assertEqual(r.status_code, 402)
        self.assertEqual(main.usage('premium-denied')['used_today'], 0)

    def test_premium_user_can_use_premium_modes_without_free_quota(self):
        uid = 'premium-allowed'
        main.user(uid, {'premium_until': (main.datetime.utcnow() + main.timedelta(days=2)).isoformat()})
        headers = auth(uid)
        for _ in range(4):
            r = client.post('/api/analyze', headers=headers, json={'user_id':uid,'module':'chat','mode':'provocativo'})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(main.usage(uid)['remaining'], 999)
        self.assertEqual(main.usage(uid)['used_today'], 0)

    def test_retry_is_reserved_then_released_after_failure(self):
        uid='retry-state'
        headers=auth(uid)
        created=client.post('/api/analyze',headers=headers,json={'user_id':uid,'module':'chat','mode':'coquetear'}).json()
        payload={'analysis_id':created['analysis_id'],'text':'hola'}
        self.assertEqual(client.post('/api/retry',headers=headers,json=payload).status_code,200)
        c=main.db(); value=c.execute('SELECT retry_used FROM analysis_attempts WHERE id=?',(created['analysis_id'],)).fetchone()[0]; c.close()
        self.assertEqual(value,1)
        self.assertEqual(client.post('/api/retry/release',headers=headers,json=payload).status_code,200)
        c=main.db(); value=c.execute('SELECT retry_used FROM analysis_attempts WHERE id=?',(created['analysis_id'],)).fetchone()[0]; c.close()
        self.assertEqual(value,0)


    def test_retry_release_cannot_reset_a_successful_retry(self):
        from unittest.mock import patch
        uid = 'retry-release-abuse'
        headers = auth(uid)
        created = client.post('/api/analyze', headers=headers, json={
            'user_id': uid, 'module': 'chat', 'mode': 'coquetear'
        })
        self.assertEqual(created.status_code, 200, created.text)
        aid = created.json()['analysis_id']
        payload = {
            'user_id': uid, 'module': 'chat', 'mode': 'coquetear',
            'text': '¿Qué haces hoy?', 'analysis_id': aid,
        }
        with patch.object(main, 'ai_generate_reply', return_value={
            'reply': 'Podríamos hablar un rato.',
            'alternative': '¿Tienes algún plan para hoy?',
            'provider': 'test-provider',
        }):
            first = client.post('/api/generate-reply', headers=headers, json=payload)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(client.post('/api/retry', headers=headers, json={
                'analysis_id': aid, 'text': payload['text']
            }).status_code, 200)
            second = client.post('/api/generate-reply', headers=headers, json=payload)
            self.assertEqual(second.status_code, 200, second.text)

        released = client.post('/api/retry/release', headers=headers, json={
            'analysis_id': aid, 'text': payload['text']
        })
        self.assertEqual(released.status_code, 200, released.text)
        self.assertFalse(released.json()['released'])
        again = client.post('/api/retry', headers=headers, json={
            'analysis_id': aid, 'text': payload['text']
        })
        self.assertEqual(again.status_code, 409, again.text)

    def test_retry_cannot_be_claimed_twice(self):
        uid='retry-once'
        headers=auth(uid)
        created=client.post('/api/analyze',headers=headers,json={'user_id':uid,'module':'chat','mode':'coquetear'}).json()
        payload={'analysis_id':created['analysis_id'],'text':'hola'}
        self.assertEqual(client.post('/api/retry',headers=headers,json=payload).status_code,200)
        self.assertEqual(client.post('/api/retry',headers=headers,json=payload).status_code,409)


class TestAIProviderRetries(unittest.TestCase):
    def test_provider_retry_after_and_temporary_retry(self):
        from unittest.mock import patch
        import ai_providers
        from urllib.error import HTTPError
        import email.message
        headers=email.message.Message(); headers['Retry-After']='0'
        errors=[ai_providers.ProviderError('busy',True,0), 'ok']
        def call():
            value=errors.pop(0)
            if isinstance(value, Exception): raise value
            return value
        with patch.object(ai_providers.time,'sleep') as sleep:
            self.assertEqual(ai_providers._with_retry(call),'ok')
            sleep.assert_called_once_with(0)

    def test_permanent_provider_error_is_not_retried(self):
        from unittest.mock import patch
        import ai_providers
        call_count=[0]
        def call():
            call_count[0]+=1
            raise ai_providers.ProviderError('bad request',False)
        with patch.object(ai_providers.time,'sleep') as sleep:
            with self.assertRaises(ai_providers.ProviderError): ai_providers._with_retry(call)
            self.assertEqual(call_count[0],1)
            sleep.assert_not_called()

class TestVisualAnalysis(unittest.TestCase):
    def test_chat_and_story_forward_visual_context_to_shared_provider(self):
        from unittest.mock import patch
        uid='visual-premium'
        main.user(uid, {'premium_until': (main.datetime.utcnow() + main.timedelta(days=2)).isoformat()})
        headers=auth(uid)
        image='data:image/jpeg;base64,' + ('a' * 64)
        for module, mode in [('chat','coquetear'),('story','gracioso')]:
            attempt=client.post('/api/analyze',headers=headers,json={'user_id':uid,'module':module,'mode':mode})
            self.assertEqual(attempt.status_code,200,attempt.text)
            with patch.object(main, 'ai_generate_reply', return_value={'reply':'Respuesta contextual','alternative':'Otra alternativa','provider':'gemini'}) as provider:
                r=client.post('/api/generate-reply', headers=headers, json={'user_id':uid,'module':module,'mode':mode,'text':'texto OCR','image':image,'analysis_id':attempt.json()['analysis_id']})
                self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(r.json()['reply'],'Respuesta contextual')
                self.assertEqual(r.json()['alternative'],'Otra alternativa')
                self.assertEqual(r.json()['provider'],'gemini')
                self.assertEqual(r.json()['model'], 'gemini-3.8-flash')
                self.assertGreaterEqual(r.json()['quality_score'], 1)
                self.assertLessEqual(r.json()['quality_score'], 100)
                conn=main.db()
                event=conn.execute("SELECT * FROM ai_generation_events WHERE analysis_id=? ORDER BY id DESC LIMIT 1",(attempt.json()['analysis_id'],)).fetchone()
                conn.close()
                self.assertIsNotNone(event)
                self.assertEqual(event['status'],'success')
                self.assertEqual(event['provider'],'gemini')
                self.assertNotIn('texto OCR', str(dict(event)))
                self.assertEqual(provider.call_args.args[2],module)
                self.assertEqual(provider.call_args.args[3],image)


    def test_visual_provider_failure_falls_back_to_ocr_and_text_provider(self):
        from unittest.mock import patch
        uid = 'visual-ocr-fallback'
        headers = auth(uid)
        attempt = client.post('/api/analyze', headers=headers, json={
            'user_id': uid, 'module': 'chat', 'mode': 'coquetear'
        })
        self.assertEqual(attempt.status_code, 200, attempt.text)
        image = 'data:image/jpeg;base64,' + ('a' * 64)
        fallback = {
            'reply': 'Podríamos hablar un rato.',
            'alternative': '¿Qué planes tienes hoy?',
            'provider': 'groq',
        }
        recognized = '¿Quieres salir a cenar?'
        with patch.object(main, 'ai_generate_reply', side_effect=[
            main.ProviderError('No hay un proveedor de IA con visión configurado.'),
            fallback,
        ]) as provider, patch.object(main, '_decode_ocr_image', return_value='decoded-image') as decoder, patch.object(main, '_ocr_text', return_value=recognized) as ocr:
            response = client.post('/api/generate-reply', headers=headers, json={
                'user_id': uid, 'module': 'chat', 'mode': 'coquetear',
                'text': '', 'image': image, 'analysis_id': attempt.json()['analysis_id'],
            })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reply'], fallback['reply'])
        self.assertEqual(response.json()['provider'], 'groq')
        self.assertTrue(response.json()['ocr_fallback'])
        self.assertEqual(response.json()['ocr_text'], recognized)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(provider.call_args_list[0].args[3], image)
        self.assertEqual(provider.call_args_list[1].args[0], recognized)
        self.assertIsNone(provider.call_args_list[1].args[3])
        decoder.assert_called_once()
        ocr.assert_called_once()

        conn = main.db()
        event = conn.execute(
            'SELECT * FROM ai_generation_events WHERE analysis_id=? ORDER BY id DESC LIMIT 1',
            (attempt.json()['analysis_id'],),
        ).fetchone()
        conn.close()
        self.assertEqual(event['status'], 'success')
        self.assertEqual(event['provider'], 'groq')
        self.assertNotIn(recognized, str(dict(event)))

    def test_successful_visual_provider_does_not_run_ocr(self):
        from unittest.mock import patch
        uid = 'visual-no-ocr'
        headers = auth(uid)
        attempt = client.post('/api/analyze', headers=headers, json={
            'user_id': uid, 'module': 'chat', 'mode': 'coquetear'
        })
        image = 'data:image/jpeg;base64,' + ('a' * 64)
        with patch.object(main, 'ai_generate_reply', return_value={
            'reply': 'Respuesta contextual',
            'alternative': 'Otra respuesta contextual',
            'provider': 'gemini',
        }), patch.object(main, '_ocr_text') as ocr:
            response = client.post('/api/generate-reply', headers=headers, json={
                'user_id': uid, 'module': 'chat', 'mode': 'coquetear',
                'image': image, 'analysis_id': attempt.json()['analysis_id'],
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['ocr_fallback'])
        self.assertEqual(response.json()['ocr_text'], '')
        ocr.assert_not_called()

    def test_failed_generation_is_logged_without_raw_error_content(self):
        from unittest.mock import patch
        uid='monitor-failed-generation'
        headers=auth(uid)
        attempt=client.post('/api/analyze',headers=headers,json={'user_id':uid,'module':'chat','mode':'coquetear'})
        self.assertEqual(attempt.status_code,200,attempt.text)
        with patch.object(main, 'ai_generate_reply', side_effect=RuntimeError('secret api_key=SHOULD_NOT_BE_STORED')):
            r=client.post('/api/generate-reply',headers=headers,json={'user_id':uid,'module':'chat','mode':'coquetear','text':'hola','analysis_id':attempt.json()['analysis_id']})
        self.assertEqual(r.status_code,503)
        conn=main.db()
        event=conn.execute("SELECT * FROM ai_generation_events WHERE analysis_id=? ORDER BY id DESC LIMIT 1",(attempt.json()['analysis_id'],)).fetchone()
        conn.close()
        self.assertIsNotNone(event)
        self.assertEqual(event['status'],'error')
        self.assertEqual(event['error_code'],'RuntimeError')
        self.assertNotIn('SHOULD_NOT_BE_STORED',str(dict(event)))

    def test_invalid_visual_payload_rejected(self):
        uid='visual-invalid'; headers=auth(uid)
        r=client.post('/api/generate-reply',headers=headers,json={'user_id':uid,'module':'chat','mode':'coquetear','text':'hola','image':'data:text/plain;base64,abcd'})
        self.assertEqual(r.status_code,400)


class TestAIReplyQualityHelpers(unittest.TestCase):
    def test_prompt_prioritizes_recent_context_and_distinct_alternatives(self):
        import ai_providers
        prompt = ai_providers._build_prompt("coquetear", "chat")
        self.assertIn("mensajes más recientes", prompt)
        self.assertIn("No reinicies una conversación", prompt)
        self.assertIn("DOS alternativas realmente distintas", prompt)

    def test_parser_rejects_duplicate_replies(self):
        import ai_providers
        self.assertIsNone(ai_providers._parse_replies('{"reply":"Hola","alternative":"Hola"}'))

    def test_parser_accepts_two_distinct_replies(self):
        import ai_providers
        result = ai_providers._parse_replies('{"reply":"¿A qué hora sales?","alternative":"¿Qué planes tienes después?"}')
        self.assertEqual(result, {"reply":"¿A qué hora sales?","alternative":"¿Qué planes tienes después?"})


class TestAIMonitorSecurity(unittest.TestCase):
    def test_monitor_requires_admin_authentication(self):
        self.assertEqual(client.get('/api/admin/ai-monitor').status_code, 401)

    def test_owner_can_access_monitor_and_response_has_safe_metadata(self):
        login=client.post('/api/admin/login',json={'master_key':'dummy-admin-key-for-tests','username':'','password':''})
        self.assertEqual(login.status_code,200,login.text)
        headers={'Authorization':'Bearer '+login.json()['token']}
        r=client.get('/api/admin/ai-monitor',headers=headers)
        self.assertEqual(r.status_code,200,r.text)
        data=r.json()
        self.assertIn('summary',data)
        self.assertIn('providers',data)
        self.assertIn('users',data)
        self.assertIn('events',data)
        self.assertIn('quality_note',data)
        serialized=str(data).lower()
        self.assertNotIn('api_key',serialized)
        self.assertNotIn('texto ocr',serialized)

    def test_admin_without_ai_permission_is_forbidden(self):
        uid='limited-admin'
        salt=os.urandom(16)
        digest=salt.hex()+':'+__import__('hashlib').pbkdf2_hmac('sha256',b'long-password-123',salt,180000).hex()
        conn=main.db()
        conn.execute("INSERT INTO admin_users(username,password_hash,permissions,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (uid,digest,'["users"]',1,main.now(),main.now()))
        conn.commit(); conn.close()
        login=client.post('/api/admin/login',json={'username':uid,'password':'long-password-123','master_key':''})
        self.assertEqual(login.status_code,200,login.text)
        r=client.get('/api/admin/ai-monitor',headers={'Authorization':'Bearer '+login.json()['token']})
        self.assertEqual(r.status_code,403)
