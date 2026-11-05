"""E2E (opcional) de las mejoras de noviembre: aviso de operación activa, copiar con texto,
pantalla de comprobante, soporte en pantalla completa, teléfono (reemplazar/eliminar) y precarga de Citas.
Requiere: pip install playwright && playwright install chromium.  Uso: python tests/e2e_mejoras_noviembre.py
"""
import json, re, http.server, threading, functools, os, urllib.parse
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=http.server.ThreadingHTTPServer(('127.0.0.1',8767),functools.partial(H,directory=ROOT)); threading.Thread(target=srv.serve_forever,daemon=True).start()
S={"phone":"52677163","op":None,"calls":[],"proofs":0}
def api(route):
    req=route.request; path=req.url.split('8767')[1]; S["calls"].append(path)
    def j(o,st=200): route.fulfill(status=st,content_type='application/json',body=json.dumps(o))
    body=json.loads(req.post_data) if req.post_data and req.post_data.startswith('{') else {}
    if path=='/api/auth/telegram': return j({"success":True,"user_id":"7","token":"t","premium":False,"remaining":3})
    if path=='/api/payments/pricing': return j({"currency":"CUP","plans":{"weekly":{"amount":"2500 CUP","amount_value":2500,"days":7},"annual":{"amount":"15500 CUP","amount_value":15500,"days":365}}})
    if path=='/api/profile': return j({"user_id":"7","username":"ana","first_name":"Ana","payment_phone":S["phone"],"premium":False,"premium_until":None,"chats":1,"stories":0,"analyses":1})
    if path=='/api/usage': return j({"remaining":3,"limit":3,"premium":False})
    if path=='/api/payment-phone':
        if S["op"]: return j({"detail":"Tienes una operación de pago activa."},409)
        S["phone"]=re.sub(r'\D','',body.get('phone','')); return j({"success":True,"payment_phone":S["phone"]})
    if path=='/api/payment-phone/delete': S["phone"]=""; return j({"success":True,"payment_phone":""})
    if path=='/api/payments/pending':
        m=body.get('payment_method','BANDEC')
        if S["op"]:
            o=S["op"]; return j({"success":True,"operation_id":o["id"],"status":"pending","amount":"2500 CUP","payment_method":o["m"],"destination_account":"9244069990684435","payment_phone":S["phone"],"existing_operation":True})
        S["n"]=S.get("n",0)+1; S["op"]={"id":f"OP{S['n']}","m":m}
        return j({"success":True,"operation_id":S["op"]["id"],"status":"pending","amount":"2500 CUP","payment_method":m,"destination_account":"9244069990684435","payment_phone":S["phone"],"existing_operation":False})
    if path=='/api/payments/status': return j({"status":"pending"})
    if path=='/api/payments/proof': S["proofs"]+=1; return j({"success":True})
    if path=='/api/payments/cancel': S["op"]=None; return j({"success":True})
    if path=='/api/dating/config': return j({"provinces":["La Habana"],"genders":["hombre"],"looking_for":["todos"],"max_bio":300,"max_photos":6,"report_reasons":["fake"]})
    if path=='/api/dating/me': return j({"profile":None,"photos":[]})
    if path.startswith('/api/'): return j({})
    route.continue_()
errors=[]
def shown(): return pg.evaluate("[...document.querySelectorAll('.screen')].filter(e=>e.offsetParent!==null&&e.getBoundingClientRect().height>0).map(e=>e.id)")
def toastt(): return pg.evaluate("document.querySelector('.toast')?.textContent")
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':390,'height':780},device_scale_factor=2,permissions=['clipboard-read','clipboard-write'])
    pg=ctx.new_page(); pg.on('pageerror',lambda e:errors.append('PAGEERROR '+str(e)))
    opened=[]; pg.on('popup',lambda pp:opened.append(pp.url))
    pg.route('**/127.0.0.1:8767/api/**',api); pg.route('**/cdnjs.cloudflare.com/**',lambda r:r.abort()); pg.route('**/telegram.org/**',lambda r:r.fulfill(body='',content_type='application/javascript'))
    pg.goto('http://127.0.0.1:8767/index.html'); pg.wait_for_function("state.authToken", timeout=8000); pg.wait_for_timeout(500)
    # 7) Citas precargadas al iniciar sesión (antes de tocar la pestaña)
    pre=list(S["calls"]); assert '/api/dating/config' in pre and '/api/dating/me' in pre, pre
    print('7 precarga OK:',[c for c in pre if 'dating' in c])
    # 6) teléfono guardado -> Reemplazar / Eliminar
    pg.click('[data-nav=profile]'); pg.wait_for_timeout(400)
    assert not pg.is_hidden('#phoneSaved') and pg.is_hidden('#phoneEdit'); print('6 teléfono guardado:',pg.inner_text('#phoneSavedValue'))
    pg.click('#replacePhone'); assert not pg.is_hidden('#phoneEdit') and not pg.is_hidden('#cancelPhoneEdit')
    pg.fill('#profilePhone','5 5551234'); pg.click('#saveProfilePhone'); pg.wait_for_timeout(400)
    assert pg.inner_text('#phoneSavedValue')=='+53 55551234', pg.inner_text('#phoneSavedValue'); print('6 reemplazado ->',pg.inner_text('#phoneSavedValue'))
    pg.screenshot(path='/tmp/m_profile.png')
    # --- flujo de pago
    pg.evaluate("showPremium('general')"); pg.click('#startPayment'); pg.wait_for_timeout(200)
    pg.click('.payment-method[data-method=BPA]'); pg.wait_for_timeout(400); pg.click('#continuePaymentMethod'); pg.wait_for_timeout(500)
    assert shown()==['transferScreen'], shown()
    # 4) sin texto "Se utiliza..." + copiar con texto
    body=pg.inner_text('#transferScreen'); assert 'Se utiliza para identificar tu pago' not in body
    assert 'Copiar destino' in body and 'Copiar número' in body
    pg.click('#copyPaymentValue'); pg.wait_for_timeout(200); print('4 toast:',toastt()); assert 'Destino copiado' in toastt()
    assert pg.evaluate("navigator.clipboard.readText()")=='9244069990684435'
    pg.click('#copyConfirmNumber'); pg.wait_for_timeout(200); print('4 toast:',toastt()); assert 'Número a confirmar copiado' in toastt()
    assert pg.evaluate("navigator.clipboard.readText()")=='52677163'
    pg.screenshot(path='/tmp/m_transfer.png')
    # 4.1) comprobante en pantalla aparte
    assert pg.is_hidden('#paymentProofText') and 'Si no se encuentra tu pago' in body
    pg.click('#openProof'); pg.wait_for_timeout(250); assert shown()==['proofScreen'], shown(); pg.screenshot(path='/tmp/m_proof.png')
    pg.fill('#paymentProofText','ref 123'); pg.click('#submitProof'); pg.wait_for_timeout(500)
    assert S["proofs"]==1 and shown()==['transferScreen'], (S["proofs"],shown()); assert pg.is_hidden('#proofEntry'); print('4.1 comprobante enviado y vuelve a transferencia')
    # 3) atrás completo -> continuar -> aviso con 2 botones
    pg.click('#backFromTransfers'); pg.wait_for_timeout(250); assert shown()==['paymentMethodScreen'], shown()
    pg.click('#continuePaymentMethod'); pg.wait_for_timeout(400)
    assert not pg.is_hidden('#activePaymentModal'); print('3 aviso:',pg.inner_text('#activePaymentText')); pg.screenshot(path='/tmp/m_active.png')
    pg.click('#resumePayment'); pg.wait_for_timeout(400); assert shown()==['transferScreen'] and S["op"]["id"]=="OP1"; print('3 retomar OK')
    pg.click('#backFromTransfers'); pg.wait_for_timeout(250); pg.click('#continuePaymentMethod'); pg.wait_for_timeout(400)
    pg.click('#replacePayment'); pg.wait_for_timeout(600)
    assert shown()==['transferScreen'] and S["op"]["id"]=="OP2" and pg.evaluate("state.operationId")=="OP2"; print('3 borrar y crear nueva OK ->',S["op"]["id"])
    assert not pg.is_hidden('#proofEntry')   # operación nueva vuelve a permitir comprobante
    # 6) con operación activa no se puede cambiar el teléfono
    # 5) soporte
    pg.evaluate("hideTopScreens();screenStack.length=0;settings()"); pg.click('#contactButton'); pg.wait_for_timeout(250)
    assert shown()==['supportScreen'] and pg.is_hidden('.bottom-nav'); assert pg.is_disabled('#supportTelegram')
    reasons=pg.inner_text('#supportReasons'); assert 'Problema con un análisis' in reasons; pg.screenshot(path='/tmp/m_support0.png')
    pg.click('.support-reason >> nth=0'); assert not pg.is_disabled('#supportTelegram'); pg.screenshot(path='/tmp/m_support1.png')
    print('5 mensaje:',pg.evaluate("supportMessage()"))
    assert pg.evaluate("supportMessage()")=='Hola, buenas. Soy cliente de LiggaCuba y tengo un problema con un análisis.'
    pg.evaluate("window.open=(u)=>{window.__u=u}"); pg.click('#supportWhatsapp'); u=pg.evaluate("window.__u"); print('5 url WA:',urllib.parse.unquote(u))
    assert u.startswith('https://wa.me/5352677163?text=') and 'analisis' not in u
    pg.click('#supportTelegram'); u=pg.evaluate("window.__u"); assert u.startswith('https://t.me/pedritoficial?text=')
    pg.click('#supportBack'); pg.wait_for_timeout(250); print('5 atrás ->',shown())
    b.close()
print('ERRORS:',errors); assert not errors
print('TODO OK')
