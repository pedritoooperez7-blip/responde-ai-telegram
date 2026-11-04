"""Prueba de extremo a extremo del asistente de Citas (opcional).

Requiere: pip install playwright && playwright install chromium.
Sirve los archivos estáticos y simula la API; NO usa Telegram real ni el backend.
Uso: python tests/e2e_dating_wizard.py   (capturas en /tmp/citas_shots)
"""
import json, re, http.server, threading, os, functools, sys
from playwright.sync_api import sync_playwright
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FA=os.environ.get('FONT_AWESOME_DIR','')  # carpeta de @fortawesome/fontawesome-free (opcional: solo para ver los íconos)
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=http.server.ThreadingHTTPServer(('127.0.0.1',8765),functools.partial(H,directory=ROOT))
threading.Thread(target=srv.serve_forever,daemon=True).start()

cfg={"provinces":["Pinar del Río","Artemisa","La Habana","Mayabeque","Matanzas","Holguín","Fuera de Cuba"],"genders":["hombre","mujer","otro"],
 "looking_for":["hombres","mujeres","todos"],"min_age":18,"max_photos":6,"max_bio":300,"free_daily_likes":20,"report_reasons":["fake","other"]}
state={"profile":None,"posted":None}
def api(route):
    req=route.request; url=req.url; path=url.split('127.0.0.1:8765')[1]
    def j(obj,status=200): route.fulfill(status=status,content_type='application/json',body=json.dumps(obj))
    if path.startswith('/api/auth/telegram'): return j({"user_id":"7","token":"tok","premium":False,"remaining":3})
    if path=='/api/dating/config': return j(cfg)
    if path=='/api/dating/me':
        p=state["profile"]; return j({"profile":p,"photos":[],"free_daily_likes":20})
    if path=='/api/dating/profile':
        body=json.loads(req.post_data); state["posted"]=body
        prof=dict(body); prof.update({"public_id":"abc","age":25,"status":"active","visible":True,"telegram_username":"ana_test","whatsapp":body.get("whatsapp","")})
        state["profile"]=prof; return j({"profile":prof,"photos":[]})
    if path=='/api/dating/feed': return j({"profiles":[{"public_id":"p1","display_name":"Luis","age":28,"province":"Artemisa","municipality":"","bio":"Hola","interests":["Playa"],"photos":[],"same_province":True,"in_common":3}],"premium":False,"likes_left":18})
    if path=='/api/dating/likes': return j({"count":0,"locked":True})
    if path=='/api/dating/matches': return j({"matches":[{"match_id":1,"public_id":"p1","display_name":"Luis","age":28,"province":"Artemisa","municipality":"","photos":[],"contacts":[{"type":"whatsapp","label":"WhatsApp","url":"https://wa.me/5352677163"}]}]})
    if path.startswith('/api/'): return j({})
    route.continue_()
def fa(route):
    url=route.request.url
    if not FA: return route.abort()
    if url.endswith('all.min.css'): return route.fulfill(path=FA+'/css/all.min.css',content_type='text/css')
    m=re.search(r'/webfonts/(.+)$',url)
    if m: return route.fulfill(path=FA+'/webfonts/'+m.group(1))
    route.abort()
os.makedirs('/tmp/citas_shots',exist_ok=True)
errors=[]
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':390,'height':780},device_scale_factor=2)
    pg=ctx.new_page()
    pg.on('pageerror',lambda e:errors.append(str(e))); pg.on('console',lambda m: errors.append('console:'+m.text) if m.type=='error' else None)
    pg.route('**/127.0.0.1:8765/api/**',api); pg.route('**/cdnjs.cloudflare.com/**',fa); pg.route('**/telegram.org/**',lambda r:r.fulfill(body='',content_type='application/javascript'))
    pg.goto('http://127.0.0.1:8765/index.html'); pg.wait_for_timeout(800)
    pg.click('[data-nav=dating]'); pg.wait_for_timeout(300)
    pg.screenshot(path='/tmp/citas_shots/00_intro.png')
    pg.click('text=Crear mi perfil'); pg.wait_for_timeout(300)
    pg.screenshot(path='/tmp/citas_shots/01_gender.png')
    pg.click('.wz-opt[data-v=mujer]'); pg.wait_for_timeout(500)       # avanza solo
    assert pg.inner_text('.wz-title')=='¿Cómo te llamas?', pg.inner_text('.wz-title')
    pg.fill('input[type=text]','Ana'); pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    # menor de edad bloqueado
    pg.fill('input[type=date]','2015-01-01'); pg.wait_for_timeout(100)
    assert pg.is_disabled('.wz-foot .primary'); print('underage msg:',pg.inner_text('.wz-msg'))
    pg.fill('input[type=date]','2000-05-10'); pg.wait_for_timeout(100)
    print('age msg:',pg.inner_text('.wz-msg')); pg.screenshot(path='/tmp/citas_shots/02_birth.png')
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    assert 'Qué buscas' in pg.inner_text('.wz-title')
    pg.click('.wz-opt[data-v=serious]'); pg.click('.wz-opt[data-v=online]')
    pg.screenshot(path='/tmp/citas_shots/03_multi.png')
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)       # important: omitir
    print('skip label:',pg.inner_text('.wz-foot .primary'))
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    pg.click('.wz-opt[data-v=hombres]'); pg.wait_for_timeout(500)  # looking
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)       # ages ok
    # atrás vuelve
    pg.click('.wz-top .back-btn'); pg.wait_for_timeout(200); assert 'rango' in pg.inner_text('.wz-title'); pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    for i in range(3):   # attention (omitir), distance, first_move
        if pg.query_selector('.wz-opt[data-v=city]'): pg.click('.wz-opt[data-v=city]'); pg.wait_for_timeout(450)
        elif pg.query_selector('.wz-opt[data-v=either]'): pg.click('.wz-opt[data-v=either]'); pg.wait_for_timeout(450)
        else: pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    print('stage:',pg.inner_text('.wz-top strong'),'|',pg.inner_text('.wz-title'))
    pg.screenshot(path='/tmp/citas_shots/04_lifestyle.png')
    for v in ['office','out','small','coffee','want','balanced']:
        pg.click(f'.wz-opt[data-v={v}]'); pg.wait_for_timeout(450)
    pg.click('.wz-opt[data-v=travel]'); pg.click('.wz-opt[data-v=sport]'); pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)  # common
    pg.click('.wz-opt[data-v=smoke]'); pg.click('.wz-opt[data-v=none]'); pg.screenshot(path='/tmp/citas_shots/05_dealbreakers.png')
    assert pg.get_attribute('.wz-opt[data-v=smoke]','aria-pressed')=='false'   # "ninguna" es exclusiva
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    print('stage:',pg.inner_text('.wz-top strong'),'|',pg.inner_text('.wz-title'))
    assert pg.is_disabled('.wz-foot .primary')
    pg.click('.df-chip[data-v=Artemisa]'); pg.screenshot(path='/tmp/citas_shots/06_location.png')
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)   # about omitir
    pg.fill('textarea','Me gusta el mar'); pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    pg.fill('input[type=tel]','+53 52677163'); pg.wait_for_timeout(100); pg.screenshot(path='/tmp/citas_shots/07_contact.png')
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)
    assert pg.is_disabled('.wz-foot .primary'); print('legal btn:',pg.inner_text('.wz-foot .primary'))
    for cb in pg.query_selector_all('.wz-card input[type=checkbox]'): cb.check()
    pg.screenshot(path='/tmp/citas_shots/08_legal.png')
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(500)
    print('POST prefs:',state["posted"]["prefs"]); print('POST rest:',{k:v for k,v in state["posted"].items() if k!='prefs'})
    pg.screenshot(path='/tmp/citas_shots/09_done.png')
    assert 'listo' in pg.inner_text('.wz-title')
    pg.click('text=Agregar fotos'); pg.wait_for_timeout(300)
    assert not pg.is_hidden('.bottom-nav')
    pg.screenshot(path='/tmp/citas_shots/10_mine.png')
    def clean(tag):
        t=pg.inner_text('#datingBody'); assert 'null' not in t and '[object' not in t, (tag,t[:120])
    clean('mine')
    pg.click('#datingTabs >> text=Descubrir'); pg.wait_for_timeout(500); clean('discover'); print('discover chips:',pg.inner_text('.chips')); pg.screenshot(path='/tmp/citas_shots/13_discover.png')
    pg.click('#datingTabs >> text=Matches'); pg.wait_for_timeout(500); clean('matches'); pg.screenshot(path='/tmp/citas_shots/14_matches.png')
    pg.click('#datingTabs >> text=Mi perfil'); pg.wait_for_timeout(300)
    # edición: resumen por etapas, fecha bloqueada
    pg.click('text=Editar perfil'); pg.wait_for_timeout(300); pg.screenshot(path='/tmp/citas_shots/11_summary.png')
    pg.click('.wz-sum >> nth=0 >> .mini-btn'); pg.wait_for_timeout(200)
    pg.click('.wz-foot .primary'); pg.wait_for_timeout(200); pg.click('.wz-foot .primary'); pg.wait_for_timeout(200)    # gender -> name -> birth (bloqueada)
    print('locked:',pg.inner_text('.d-notice')[:80]); pg.screenshot(path='/tmp/citas_shots/12_locked.png')
    # inglés
    pg.evaluate("state.language='en'"); pg.reload(); pg.wait_for_timeout(600)
    b.close()
print('JS errors:',errors)
