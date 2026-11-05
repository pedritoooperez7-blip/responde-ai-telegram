"""Prueba de extremo a extremo de navegación y pago (opcional).

Recorre Premium -> método de pago -> teléfono -> transferencia -> cancelar y Citas -> Premium -> Atrás,
con la API simulada. Requiere: pip install playwright && playwright install chromium.
Uso: python tests/e2e_navegacion_pagos.py
"""
import json, re, http.server, threading, functools, sys
from playwright.sync_api import sync_playwright
import os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); FA=os.environ.get('FONT_AWESOME_DIR','')
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=http.server.ThreadingHTTPServer(('127.0.0.1',8766),functools.partial(H,directory=ROOT)); threading.Thread(target=srv.serve_forever,daemon=True).start()
S={"phone":"","op":None,"calls":[]}
def api(route):
    req=route.request; path=req.url.split('8766')[1]; S["calls"].append(path)
    def j(o,st=200): route.fulfill(status=st,content_type='application/json',body=json.dumps(o))
    body=json.loads(req.post_data) if req.post_data and req.post_data.startswith('{') else {}
    if path=='/api/auth/telegram': return j({"success":True,"user_id":"7","token":"t","premium":False,"remaining":3,"limit":3})
    if path=='/api/payments/pricing': return j({"currency":"CUP","plans":{"weekly":{"amount":"2500 CUP","amount_value":2500,"days":7},"annual":{"amount":"15500 CUP","amount_value":15500,"days":365}}})
    if path=='/api/profile': return j({"user_id":"7","username":"ana","first_name":"Ana","payment_phone":S["phone"],"premium":False,"premium_until":None,"chats":1,"stories":0,"analyses":1})
    if path=='/api/usage': return j({"remaining":3,"limit":3,"premium":False})
    if path=='/api/payment-phone': S["phone"]=re.sub(r'\D','',body.get('phone','')); return j({"success":True,"payment_phone":S["phone"]})
    if path=='/api/payments/pending':
        if not S["phone"]: return j({"detail":"Configura tu número de teléfono en Perfil antes de iniciar el pago."},400)
        S["op"]="OP123"; m=body.get('payment_method','BANDEC')
        return j({"success":True,"operation_id":"OP123","status":"pending","amount":"2500 CUP","payment_method":m,"destination_account":"9225069990000000" if m!='SALDO_MOVIL' else "","payment_phone":S["phone"]})
    if path=='/api/payments/status': return j({"status":"pending","premium":False})
    if path=='/api/payments/cancel': S["op"]=None; return j({"success":True})
    if path=='/api/dating/config': return j({"provinces":["La Habana"],"genders":["hombre","mujer","otro"],"looking_for":["hombres","mujeres","todos"],"max_bio":300,"report_reasons":["fake"]})
    if path=='/api/dating/me': return j({"profile":None,"photos":[]})
    if path.startswith('/api/'): return j({})
    route.continue_()
def fa(route):
    u=route.request.url
    if not FA: return route.abort()
    if u.endswith('all.min.css'): return route.fulfill(path=FA+'/css/all.min.css',content_type='text/css')
    m=re.search(r'/webfonts/(.+)$',u)
    return route.fulfill(path=FA+'/webfonts/'+m.group(1)) if m else route.abort()
errors=[]
def vis():  # pantallas visibles
    return pg.evaluate("[...document.querySelectorAll('.screen')].filter(e=>!e.classList.contains('hidden')).map(e=>e.id)")
def nav_hidden(): return pg.evaluate("document.querySelector('.bottom-nav').classList.contains('hidden')")

def shown(): return pg.evaluate("[...document.querySelectorAll('.screen')].filter(e=>e.offsetParent!==null&&e.getBoundingClientRect().height>0).map(e=>e.id)")

def toastt(): return pg.evaluate("document.querySelector('.toast')?.textContent")
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':390,'height':780})
    pg=ctx.new_page(); pg.on('pageerror',lambda e:errors.append('PAGEERROR '+str(e)))
    pg.route('**/127.0.0.1:8766/api/**',api); pg.route('**/cdnjs.cloudflare.com/**',fa); pg.route('**/telegram.org/**',lambda r:r.fulfill(body='',content_type='application/javascript'))
    pg.goto('http://127.0.0.1:8766/index.html'); pg.wait_for_timeout(900)
    pg.click('[data-nav=profile]'); pg.wait_for_timeout(300)
    pg.evaluate("showPremium('general')"); pg.click('#startPayment'); pg.wait_for_timeout(200)
    print('A métodos            ->',shown(),pg.evaluate("screenStack"))
    pg.click('.payment-method[data-method=BANDEC]'); pg.wait_for_timeout(500)
    print('B sin teléfono       ->',shown(),'| toast:',toastt(), '| pending:',pg.evaluate("state.pendingPaymentMethod"))
    pg.fill('#profilePhone','5 2677163'); pg.click('#saveProfilePhone'); pg.wait_for_timeout(600)
    print('C teléfono guardado  ->',shown(),'| método:',pg.evaluate("state.paymentMethod"),pg.evaluate("screenStack"))
    pg.click('#continuePaymentMethod'); pg.wait_for_timeout(600)
    print('D pago creado        ->',shown(),'| op:',pg.evaluate("state.operationId"),'| destino:',pg.inner_text('#paymentDestination'),'| método:',pg.inner_text('#paymentMethodLabel'),'| fila nº confirm visible:',pg.is_visible('#paymentConfirmNumberRow'),pg.evaluate("screenStack"))
    pg.screenshot(path='/tmp/s_transfer.png')
    pg.click('#backFromTransfers'); pg.wait_for_timeout(300); print('E atrás transfer     ->',shown(),pg.evaluate("screenStack"))
    pg.click('.payment-method[data-method=BPA]'); pg.wait_for_timeout(300); print('F cambiar método con op activa -> toast:',toastt(),'| método:',pg.evaluate("state.paymentMethod"))
    pg.click('#continuePaymentMethod'); pg.wait_for_timeout(400); print('G continuar con op   ->',shown())
    pg.on('dialog',lambda d:d.accept())
    if pg.is_visible('#cancelPayment'):
        pg.click('#cancelPayment'); pg.wait_for_timeout(600); print('H cancelar           ->',shown(),'| op:',pg.evaluate("state.operationId"))
    else: print('H botón cancelar NO visible en transferScreen')
    pg.click('#backFromPaymentMethods'); pg.wait_for_timeout(200); pg.click('#backFromPremium'); pg.wait_for_timeout(300); print('H2 volver a      ->',shown())
    # Citas -> premium -> atrás
    pg.click('[data-nav=dating]'); pg.wait_for_timeout(500); print('I citas              ->',shown())
    pg.evaluate("showPremium('general');screenStack.length=0;screenStack.push('datingScreen')"); pg.wait_for_timeout(200); print('J citas->premium     ->',shown(),pg.evaluate("screenStack"))
    pg.click('#backFromPremium'); pg.wait_for_timeout(300); print('K atrás              ->',shown(),'navOculta',nav_hidden())
    b.close()
print('errores',errors)
