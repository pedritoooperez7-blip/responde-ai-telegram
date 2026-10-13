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


def valid_image_data_url():
    """Small real JPEG fixture for image-validation and visual-flow tests."""
    image = main.Image.new("RGB", (2, 2), (240, 240, 240))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


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

    def test_ocr_base64_requires_auth(self):
        self.assertEqual(client.post("/ocr-base64", json={"image": "data:image/png;base64,AAAA"}).status_code, 401)

    def test_ocr_rejects_invalid_image_safely(self):
        r = client.post("/ocr", headers=auth("ocr-user"), content=b"not an image")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Imagen inválida o dañada")

    def test_ocr_stream_size_limit(self):
        r = client.post("/ocr", headers=auth("ocr-large"), content=b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(r.status_code, 413)

    def test_base64_ocr_size_limit(self):
        oversized = base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode()
        r = client.post("/ocr-base64", headers=auth("ocr-base64-large"), json={"image":oversized})
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
        main.user(uid, {'premium_until': (main.datetime.now(main.timezone.utc) + main.timedelta(days=2)).isoformat()})
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
    def test_invalid_image_payload_is_rejected_before_provider_call(self):
        from unittest.mock import patch
        uid = "visual-invalid-payload"
        headers = auth(uid)
        attempt = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        })
        self.assertEqual(attempt.status_code, 200, attempt.text)
        with patch.object(main, "ai_generate_reply") as provider:
            response = client.post("/api/generate-reply", headers=headers, json={
                "user_id": uid, "module": "chat", "mode": "coquetear",
                "text": "hola", "image": "data:image/jpeg;base64,not-valid-base64!",
                "analysis_id": attempt.json()["analysis_id"],
            })
        self.assertEqual(response.status_code, 400, response.text)
        provider.assert_not_called()

    def test_chat_and_story_forward_visual_context_to_shared_provider(self):
        from unittest.mock import patch
        uid='visual-premium'
        main.user(uid, {'premium_until': (main.datetime.now(main.timezone.utc) + main.timedelta(days=2)).isoformat()})
        headers=auth(uid)
        image=valid_image_data_url()
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
        image = valid_image_data_url()
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
        image = valid_image_data_url()
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


class TestCompleteAIFlow(unittest.TestCase):
    def test_invalid_image_is_rejected_before_daily_quota_is_charged(self):
        uid = "invalid-image-no-quota"
        headers = auth(uid)
        before = main.usage(uid)["used_today"]
        response = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear",
            "image": "data:image/jpeg;base64,bm90LWEtanBlZw==",
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(main.usage(uid)["used_today"], before)

    def test_idempotency_replays_saved_response_without_second_provider_call(self):
        from unittest.mock import patch
        uid = "idempotent-generation"
        headers = auth(uid)
        analysis = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        }).json()
        payload = {
            "user_id": uid, "module": "chat", "mode": "coquetear",
            "analysis_id": analysis["analysis_id"], "text": "¿Qué haces hoy?",
            "idempotency_key": "stable-test-key-0001",
        }
        result = {"reply": "Podemos hablar un rato.", "alternative": "¿Tienes algún plan?", "provider": "test-provider"}
        with patch.object(main, "ai_generate_reply", return_value=result) as provider:
            first = client.post("/api/generate-reply", headers=headers, json=payload)
            second = client.post("/api/generate-reply", headers=headers, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), second.json())
        provider.assert_called_once()

    def test_idempotency_key_cannot_be_reused_for_different_payload(self):
        from unittest.mock import patch
        uid = "idempotency-payload-mismatch"
        headers = auth(uid)
        analysis = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        }).json()
        payload = {"user_id": uid, "module": "chat", "mode": "coquetear",
                   "analysis_id": analysis["analysis_id"], "text": "Hola", "idempotency_key": "stable-test-key-0002"}
        with patch.object(main, "ai_generate_reply", return_value={"reply": "Hola, ¿cómo va?", "alternative": "¿Qué tal?", "provider": "test-provider"}):
            self.assertEqual(client.post("/api/generate-reply", headers=headers, json=payload).status_code, 200)
            payload["text"] = "Un contenido diferente"
            response = client.post("/api/generate-reply", headers=headers, json=payload)
        self.assertEqual(response.status_code, 409, response.text)

    def test_first_provider_failure_refunds_free_quota(self):
        from unittest.mock import patch
        uid = "provider-failure-refund"
        headers = auth(uid)
        before = main.usage(uid)["used_today"]
        analysis = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        }).json()
        self.assertEqual(main.usage(uid)["used_today"], before + 1)
        with patch.object(main, "ai_generate_reply", side_effect=main.ProviderError("provider unavailable")):
            response = client.post("/api/generate-reply", headers=headers, json={
                "user_id": uid, "module": "chat", "mode": "coquetear",
                "analysis_id": analysis["analysis_id"], "text": "Hola", "idempotency_key": "failure-refund-0001"
            })
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(main.usage(uid)["used_today"], before)

    def test_stale_generation_lock_is_recovered(self):
        from unittest.mock import patch
        uid = "stale-generation-lock"
        headers = auth(uid)
        analysis = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        }).json()
        c = main.db()
        c.execute("UPDATE analysis_attempts SET generation_in_progress=1,generation_started_at=? WHERE id=?",
                  ((main.datetime.now(main.timezone.utc)-main.timedelta(minutes=5)).isoformat(), analysis["analysis_id"]))
        c.commit(); c.close()
        with patch.object(main, "ai_generate_reply", return_value={"reply": "Respuesta uno", "alternative": "Respuesta dos", "provider": "test-provider"}):
            response = client.post("/api/generate-reply", headers=headers, json={
                "user_id": uid, "module": "chat", "mode": "coquetear",
                "analysis_id": analysis["analysis_id"], "text": "Hola", "idempotency_key": "stale-lock-0001"
            })
        self.assertEqual(response.status_code, 200, response.text)

    def test_event_logging_failure_does_not_break_success_response(self):
        from unittest.mock import patch
        import sqlite3
        uid = "event-log-db-failure"
        headers = auth(uid)
        analysis = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        }).json()
        real_db = main.db
        calls = {"count": 0}
        def fail_only_event_db():
            calls["count"] += 1
            # reservation and final lock use the first two connections; event logging is third.
            if calls["count"] == 3:
                raise sqlite3.OperationalError("test db logging failure")
            return real_db()
        with patch.object(main, "ai_generate_reply", return_value={
            "reply": "Respuesta uno", "alternative": "Respuesta dos", "provider": "test-provider"
        }), patch.object(main, "db", side_effect=fail_only_event_db):
            response = client.post("/api/generate-reply", headers=headers, json={
                "user_id": uid, "module": "chat", "mode": "coquetear",
                "analysis_id": analysis["analysis_id"], "text": "Hola", "idempotency_key": "event-log-failure-0001"
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["reply"], "Respuesta uno")


class TestImageValidationMatrix(unittest.TestCase):
    def _data_url(self, fmt, mime=None, size=(8, 8)):
        image = main.Image.new("RGB", size, (235, 235, 235))
        buffer = io.BytesIO()
        image.save(buffer, format=fmt)
        raw = buffer.getvalue()
        mime = mime or main.Image.MIME.get(fmt)
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii"), raw

    def test_every_supported_image_format(self):
        for fmt in ("PNG", "JPEG", "WEBP", "BMP", "TIFF"):
            with self.subTest(fmt=fmt):
                try:
                    data_url, raw = self._data_url(fmt)
                    self.assertEqual(main._validate_image_data_url(data_url), raw)
                except (OSError, ValueError) as exc:
                    self.skipTest(f"Pillow build cannot encode {fmt}: {exc}")

    def test_mime_matching_is_case_insensitive_and_alias_is_normalized(self):
        data_url, raw = self._data_url("PNG")
        header, payload = data_url.split(",", 1)
        self.assertEqual(main._validate_image_data_url(header.upper() + "," + payload), raw)
        jpeg, jpeg_raw = self._data_url("JPEG", "image/jpg")
        self.assertEqual(main._validate_image_data_url(jpeg), jpeg_raw)

    def test_exact_byte_limit_is_accepted_and_one_byte_over_is_rejected(self):
        data_url, raw = self._data_url("PNG")
        with unittest.mock.patch.object(main, "MAX_OCR_BYTES", len(raw)):
            self.assertEqual(main._validate_image_data_url(data_url), raw)
        with unittest.mock.patch.object(main, "MAX_OCR_BYTES", len(raw) - 1):
            with self.assertRaises(main.HTTPException) as error:
                main._validate_image_data_url(data_url)
        self.assertEqual(error.exception.status_code, 400)

    def test_pixel_limit_is_enforced_at_boundary(self):
        data_url, _ = self._data_url("PNG", size=(2, 2))
        with unittest.mock.patch.object(main, "MAX_OCR_PIXELS", 4):
            main._validate_image_data_url(data_url)
        with unittest.mock.patch.object(main, "MAX_OCR_PIXELS", 3):
            with self.assertRaises(main.HTTPException):
                main._validate_image_data_url(data_url)

    def test_truncated_and_malformed_images_are_rejected(self):
        data_url, _ = self._data_url("PNG")
        header, payload = data_url.split(",", 1)
        damaged = header + "," + payload[:-12]
        with self.assertRaises(main.HTTPException):
            main._validate_image_data_url(damaged)
        with self.assertRaises(main.HTTPException):
            main._validate_image_data_url("data:image/png;base64,%%%not-base64%%")


class TestSameAnalysisConcurrency(unittest.TestCase):
    def test_only_one_generation_runs_for_same_analysis_at_a_time(self):
        from unittest.mock import patch
        import threading
        from concurrent.futures import ThreadPoolExecutor
        uid = "same-analysis-concurrency"
        headers = auth(uid)
        analysis = client.post("/api/analyze", headers=headers, json={
            "user_id": uid, "module": "chat", "mode": "coquetear"
        }).json()
        entered = threading.Event()
        release = threading.Event()
        def slow_provider(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test timeout")
            return {"reply": "Respuesta uno", "alternative": "Respuesta dos", "provider": "test-provider"}
        payload = {"user_id": uid, "module": "chat", "mode": "coquetear", "analysis_id": analysis["analysis_id"], "text": "Hola"}
        with patch.object(main, "ai_generate_reply", side_effect=slow_provider):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(client.post, "/api/generate-reply", headers=headers, json={**payload, "idempotency_key": "concurrent-key-one"})
                self.assertTrue(entered.wait(3), "provider call did not start")
                second = client.post("/api/generate-reply", headers=headers, json={**payload, "idempotency_key": "concurrent-key-two"})
                release.set()
                first_result = first.result(timeout=8)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(first_result.status_code, 200, first_result.text)


class TestSyntheticTelegramScreenshotOCR(unittest.TestCase):
    def _screenshot_data_url(self):
        from PIL import ImageDraw, ImageFont
        canvas = main.Image.new("RGB", (900, 520), (238, 242, 247))
        draw = ImageDraw.Draw(canvas)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        try:
            font = ImageFont.truetype(font_path, 26)
        except OSError:
            font = ImageFont.load_default()
        draw.rounded_rectangle((30, 45, 600, 135), radius=20, fill=(255, 255, 255))
        draw.text((52, 70), "Hola, que haces hoy?", font=font, fill=(20, 20, 20))
        draw.rounded_rectangle((270, 175, 860, 275), radius=20, fill=(190, 235, 205))
        draw.text((292, 205), "Estoy pensando en salir un rato", font=font, fill=(20, 20, 20))
        draw.rounded_rectangle((30, 315, 660, 405), radius=20, fill=(255, 255, 255))
        draw.text((52, 340), "Quieres venir conmigo?", font=font, fill=(20, 20, 20))
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    def test_real_tesseract_ocr_reads_synthetic_telegram_style_capture(self):
        if not __import__("shutil").which("tesseract"):
            self.skipTest("Tesseract is not installed")
        image_data_url = self._screenshot_data_url()
        raw = base64.b64decode(image_data_url.split(",", 1)[1])
        recognized = main._ocr_text(main._decode_ocr_image(raw)).casefold()
        self.assertTrue("haces" in recognized or "haces hoy" in recognized, recognized)
        self.assertTrue("salir" in recognized or "venir" in recognized, recognized)

    def test_real_ocr_fallback_calls_text_provider_after_visual_failure(self):
        from unittest.mock import patch
        image_data_url = self._screenshot_data_url()
        expected = {"reply": "Podrías decirle que te gustaría ir.", "alternative": "Suena bien, ¿a qué hora?", "provider": "test-text"}
        with patch.object(main, "ai_generate_reply", side_effect=[main.ProviderError("vision down"), expected]) as provider:
            result, recognized = main._generate_with_ocr_fallback("", "coquetear", "chat", image_data_url)
        self.assertEqual(result, expected)
        self.assertTrue(recognized)
        self.assertEqual(provider.call_count, 2)
        self.assertIsNone(provider.call_args_list[1].args[3])
        self.assertTrue(provider.call_args_list[1].args[0])


class TestRetentionPolicy(unittest.TestCase):
    def test_expired_idempotency_and_old_logs_are_purged(self):
        from unittest.mock import patch
        uid = "retention-policy"
        now = main.datetime.now(main.timezone.utc)
        old_idem = (now - main.timedelta(hours=25)).isoformat()
        old_event = (now - main.timedelta(days=31)).isoformat()
        old_audit = (now - main.timedelta(days=91)).isoformat()
        c = main.db()
        c.execute("INSERT OR REPLACE INTO ai_idempotency(user_id,idempotency_key,payload_hash,status,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (uid, "expired-key", "hash", "completed", '{"reply":"private"}', old_idem, old_idem))
        c.execute("INSERT INTO ai_generation_events(user_id,status,latency_ms,created_at) VALUES(?,?,?,?)", (uid, "success", 1, old_event))
        c.execute("INSERT INTO admin_audit(actor,action,target,details,created_at) VALUES(?,?,?,?,?)", ("test", "test", uid, "{}", old_audit))
        c.commit(); c.close()
        main.purge_expired_records()
        c = main.db()
        idem_count = c.execute("SELECT COUNT(*) n FROM ai_idempotency WHERE user_id=? AND idempotency_key='expired-key'", (uid,)).fetchone()["n"]
        event_count = c.execute("SELECT COUNT(*) n FROM ai_generation_events WHERE user_id=? AND created_at=?", (uid, old_event)).fetchone()["n"]
        audit_count = c.execute("SELECT COUNT(*) n FROM admin_audit WHERE actor='test' AND created_at=?", (old_audit,)).fetchone()["n"]
        c.close()
        self.assertEqual(idem_count, 0)
        self.assertEqual(event_count, 0)
        self.assertEqual(audit_count, 0)


class TestQuotaRecovery(unittest.TestCase):
    def test_retrying_same_analysis_after_provider_failure_reserves_quota_again(self):
        from unittest.mock import patch
        uid = "quota-re-reserve"
        headers = auth(uid)
        before = main.usage(uid)["used_today"]
        analysis = client.post("/api/analyze", headers=headers, json={"user_id": uid, "module": "chat", "mode": "coquetear"}).json()
        with patch.object(main, "ai_generate_reply", side_effect=main.ProviderError("provider down")):
            failed = client.post("/api/generate-reply", headers=headers, json={"user_id": uid, "module": "chat", "mode": "coquetear", "analysis_id": analysis["analysis_id"], "text": "Hola", "idempotency_key": "quota-fail-key"})
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(main.usage(uid)["used_today"], before)
        with patch.object(main, "ai_generate_reply", return_value={"reply": "Respuesta uno", "alternative": "Respuesta dos", "provider": "test-provider"}):
            success = client.post("/api/generate-reply", headers=headers, json={"user_id": uid, "module": "chat", "mode": "coquetear", "analysis_id": analysis["analysis_id"], "text": "Hola", "idempotency_key": "quota-success-key"})
        self.assertEqual(success.status_code, 200, success.text)
        self.assertEqual(main.usage(uid)["used_today"], before + 1)

    def test_client_can_release_quota_if_generation_never_started(self):
        uid = "quota-release-client"
        headers = auth(uid)
        before = main.usage(uid)["used_today"]
        analysis = client.post("/api/analyze", headers=headers, json={"user_id": uid, "module": "chat", "mode": "coquetear"}).json()
        self.assertEqual(main.usage(uid)["used_today"], before + 1)
        released = client.post("/api/analyze/release", headers=headers, json={"analysis_id": analysis["analysis_id"], "text": ""})
        self.assertEqual(released.status_code, 200, released.text)
        self.assertTrue(released.json()["released"])
        self.assertEqual(main.usage(uid)["used_today"], before)
