const tg=window.Telegram?.WebApp;
const state={authToken:sessionStorage.getItem('liggacuba_auth')||'',paymentMethod:"BANDEC",paymentPhone:"",paymentPricing:null,module:'chat',file:null,mode:'coquetear',userId:String(tg?.initDataUnsafe?.user?.id||'guest-user'),premium:false,premiumUntil:null,remaining:0,language:localStorage.getItem('liggacuba_lang')||'es',plan:'weekly',operationId:null,lastAnalysisText:'',lastReply1:'',lastReply2:'',lastProvider:'',lastOCRText:'',lastAnalysisImage:null,retryUsed:false,analysisModule:'chat',lastAnalysisId:null,lastGenerationKey:null};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];const formatCubaDate=v=>{if(!v)return '—';const d=new Date(v);return Number.isNaN(d.getTime())?String(v):new Intl.DateTimeFormat(state.language==='es'?'es-CU':'en-US',{timeZone:'America/Havana',dateStyle:'medium',timeStyle:'short'}).format(d)};
const modes={chat:[['gracioso','fa-face-grin-stars',false],['coquetear','fa-face-smile-wink',false],['provocativo','fa-bolt',true],['enamorar','fa-heart',false],['salvar','fa-life-ring',true],['reactivar','fa-rotate-right',true]],story:[['gracioso','fa-face-grin-stars',false],['coquetear','fa-face-smile-wink',false],['provocativo','fa-bolt',true],['enamorar','fa-heart',true],['reactivar','fa-rotate-right',true]]};
const labels={es:{gracioso:'Gracioso',coquetear:'Coquetear',provocativo:'Provocativo',enamorar:'Enamorar',salvar:'Salvar Situación'},en:{gracioso:'Funny',coquetear:'Flirt',provocativo:'Provocative',enamorar:'Romantic',salvar:'Save Situation'}};
const i18n={es:{loading:'Cargando...',chat:'Chat',story:'Estado Story',chat_image:'Imagen de la conversación',chat_help:'Sube una captura de tu chat',story_image:'Captura del estado',story_help:'Sube una captura del estado para responder',add:'Agregar',replace:'Reemplazar',delete:'Eliminar',mode:'Modo de respuesta',mode_help:'Elige el estilo de tu respuesta',refresh:'Actualizar',analyze:'Analizar con LiggaCuba',back:'Atrás',profile_sub:'Tu asistente para conversaciones',stats_chats:'Chats',stats_stories:'Historias',stats_total:'Análisis',premium:'Premium',premium_title:'Desbloquea todo el poder',premium_desc:'Respuestas más completas, todos los modos y sin límite diario.',get_premium:'Obtener Premium',settings:'Configuración',language:'Idioma',contact:'Contáctanos',more:'Más',weekly:'Semanal',monthly:'Mensual',annual:'Anual',seven_days:'7 días',thirty_days:'30 días',annual_save:'365 días · 1 año',stats_title:'Mis estadísticas',stats_best_mode:'Mejor modo',stats_this_week:'Esta semana',stats_total_all:'Total análisis',refer_title:'Invita y gana',refer_desc:'Comparte tu código. Cuando tu amigo active Premium, tú ganas 3 días gratis.',refer_code_label:'Tu código de referido',refer_copy:'Copiar código',refer_copied:'¡Copiado!',refer_friends:'Amigos invitados',refer_rewarded:'Recompensas ganadas',refer_apply_title:'¿Tienes un código?',refer_apply_placeholder:'Código de referido',refer_apply_btn:'Aplicar código',refer_apply_ok:'¡Código aplicado! Activa Premium para que tu amigo reciba su recompensa.',premium_benefit1:'Análisis ilimitados',premium_benefit2:'Todos los modos de respuesta',premium_benefit3:'Salvar Situación incluido',premium_benefit4:'Acceso a funciones Premium futuras',choose_plan:'Elige tu plan',payment_confirm_number:'Número a confirmar',payment_confirm_help:'Se utiliza para identificar tu pago.',payment_phone_required:'Configura tu número de teléfono en Perfil antes de continuar.',payment_method_title:'Método de pago',payment_method_help:'Elige cómo quieres pagar tu Premium',continue_to_transfer:'Continuar a los datos de pago',transfer_title:'Datos de la transferencia',transfer_help:'Comprueba los datos y completa tu pago',payment_method_locked:'Ya existe una operación de pago. Cancélala antes de cambiar el método.',continue_payment:'Continuar con Premium',payment_title:'Activa tu Premium',payment_help:'Paga con el importe exacto. La confirmación automática funciona en paralelo con la revisión manual.',proof_placeholder:'Referencia o datos del pago (opcional)',proof_image:'Foto del comprobante',send_proof:'Enviar comprobante',payment_instructions:'Realiza la transferencia con el importe exacto. Espera la confirmación automática o envía el comprobante para revisión manual.',manual_review_help:'El comprobante será revisado por administración. Enviar un comprobante no activa Premium automáticamente.',waiting:'Comprobante enviado. Estamos esperando verificación.',cancel_payment:'Cancelar operación',create_payment:'Crear operación de pago',crop_title:'Ajustar captura',crop_help:'Mueve y ajusta el recorte para dejar visible solo la conversación.',cancel:'Cancelar',use:'Usar recorte',result:'Resultado',recognized:'Texto reconocido',ligga_reply:'Respuesta de LiggaCuba',copy:'Copiar',another:'Analizar otra',support:'Centro de Soporte',support_help:'Elige una vía de contacto.',privacy:'Política de Privacidad',terms:'Términos de Uso',about:'Sobre LiggaCuba',more_help:'Información y recursos',home:'Inicio',dating:'Citas',profile:'Perfil',more_screen:'Más',premium_active:'Premium activo',premium_until:'Activo hasta',free_plan:'Plan gratuito',free_help:'3 análisis diarios',go_premium:'Mejorar a Premium',no_more:'Has usado tus 3 análisis gratuitos de hoy.',no_text:'No pude leer texto suficiente. Ajusta el recorte o usa una captura más clara.',premium_only:'Este modo es exclusivo de Premium.',support_telegram:'Telegram · @pedritoficial',support_whatsapp:'WhatsApp · +53 52677163'},en:{loading:'Loading...',chat:'Chat',story:'Story Status',chat_image:'Conversation image',chat_help:'Upload a screenshot of your chat',story_image:'Story screenshot',story_help:'Upload a story screenshot to reply',add:'Add',replace:'Replace',delete:'Delete',mode:'Response mode',mode_help:'Choose your response style',refresh:'Refresh',analyze:'Analyze with LiggaCuba',back:'Back',profile_sub:'Your conversation assistant',stats_chats:'Chats',stats_stories:'Stories',stats_total:'Analyses',premium:'Premium',premium_title:'Unlock the full power',premium_desc:'Better responses, every mode and no daily limit.',get_premium:'Get Premium',settings:'Settings',language:'Language',contact:'Contact us',more:'More',weekly:'Weekly',monthly:'Monthly',annual:'Annual',seven_days:'7 days',thirty_days:'30 days',annual_save:'365 days · 1 year',stats_title:'My statistics',stats_best_mode:'Best mode',stats_this_week:'This week',stats_total_all:'Total analyses',refer_title:'Invite & earn',refer_desc:'Share your code. When your friend activates Premium, you get 3 free days.',refer_code_label:'Your referral code',refer_copy:'Copy code',refer_copied:'Copied!',refer_friends:'Friends invited',refer_rewarded:'Rewards earned',refer_apply_title:'Have a code?',refer_apply_placeholder:'Referral code',refer_apply_btn:'Apply code',refer_apply_ok:'Code applied! Activate Premium so your friend gets their reward.',premium_benefit1:'Unlimited analyses',premium_benefit2:'All response modes',premium_benefit3:'Save Situation included',premium_benefit4:'Access to future Premium features',choose_plan:'Choose your plan',payment_confirm_number:'Number to confirm',payment_confirm_help:'Used to identify your payment.',payment_phone_required:'Add your phone number in Profile before continuing.',payment_method_title:'Payment method',payment_method_help:'Choose how you want to pay for Premium',continue_to_transfer:'Continue to payment details',transfer_title:'Transfer details',transfer_help:'Review the details and complete your payment',payment_method_locked:'A payment operation already exists. Cancel it before changing the method.',continue_payment:'Continue to Premium',payment_title:'Activate Premium',payment_help:'Pay the exact amount. Automatic confirmation works alongside manual review.',proof_placeholder:'Payment reference or details (optional)',proof_image:'Receipt photo',send_proof:'Submit proof',payment_instructions:'Transfer the exact amount. Wait for automatic confirmation or submit proof for manual review.',manual_review_help:'The receipt will be reviewed by an administrator. Submitting proof does not activate Premium automatically.',waiting:'Proof submitted. We are waiting for verification.',cancel_payment:'Cancel operation',create_payment:'Create payment operation',crop_title:'Adjust screenshot',crop_help:'Move and adjust the crop to keep only the conversation visible.',cancel:'Cancel',use:'Use crop',result:'Result',recognized:'Recognized text',ligga_reply:'LiggaCuba reply',copy:'Copy',another:'Analyze another',support:'Support Center',support_help:'Choose a contact method.',privacy:'Privacy Policy',terms:'Terms of Use',about:'About LiggaCuba',more_help:'Information and resources',home:'Home',dating:'Dating',profile:'Profile',more_screen:'More',premium_active:'Premium active',premium_until:'Active until',free_plan:'Free plan',free_help:'3 analyses per day',go_premium:'Upgrade to Premium',no_more:'You have used your 3 free analyses today.',no_text:'I could not read enough text. Adjust the crop or use a clearer screenshot.',premium_only:'This mode is exclusive to Premium.',support_telegram:'Telegram · @pedritoficial',support_whatsapp:'WhatsApp · +53 52677163'}};
const i18nExtra={
es:{payment_destination:'Destino',copy_destination:'Copiar destino',copy_number:'Copiar número',destination_copied:'Destino copiado',number_copied:'Número a confirmar copiado',
 proof_entry_text:'Si no se encuentra tu pago, utiliza nuestro sistema de envío de comprobante.',proof_screen_title:'Enviar comprobante',proof_screen_help:'Adjunta la foto o los datos de tu pago para que administración lo revise.',
 active_payment_title:'Tienes una operación de pago activa',resume_operation:'Retomar operación',delete_and_new:'Borrar y crear nueva',
 phone_label:'Tu número de teléfono',phone_save:'Guardar',phone_replace:'Reemplazar',phone_delete:'Eliminar',phone_help:'Se guarda en tu perfil y se utiliza para identificar los pagos.',cancel:'Cancelar',
 phone_deleted:'Número eliminado',phone_delete_confirm:'¿Eliminar tu número de teléfono? Tendrás que agregarlo de nuevo para pagar.',
 support:'Centro de Soporte',support_reason_help:'Elige el motivo de tu consulta.',support_contact_by:'Contactar por',support_pick_reason:'Selecciona un motivo para continuar.',support_ready:'Se abrirá el chat con el mensaje ya escrito.'},
en:{payment_destination:'Destination',copy_destination:'Copy destination',copy_number:'Copy number',destination_copied:'Destination copied',number_copied:'Confirmation number copied',
 proof_entry_text:"If your payment can't be found, use our proof-of-payment submission system.",proof_screen_title:'Send proof of payment',proof_screen_help:'Attach a photo or the details of your payment so an admin can review it.',
 active_payment_title:'You have an active payment operation',resume_operation:'Resume operation',delete_and_new:'Delete and create new',
 phone_label:'Your phone number',phone_save:'Save',phone_replace:'Replace',phone_delete:'Delete',phone_help:'Saved to your profile and used to identify payments.',cancel:'Cancel',
 phone_deleted:'Number deleted',phone_delete_confirm:'Delete your phone number? You will need to add it again to pay.',
 support:'Support Center',support_reason_help:'Choose the reason for your request.',support_contact_by:'Contact via',support_pick_reason:'Select a reason to continue.',support_ready:'The chat will open with the message already written.'}
};
Object.assign(i18n.es,i18nExtra.es);Object.assign(i18n.en,i18nExtra.en);
const supportReasons=[
 {id:'analysis',icon:'fa-wand-magic-sparkles',es:'Problema con un análisis',en:'Problem with an analysis',msg_es:'tengo un problema con un análisis',msg_en:'I have a problem with an analysis'},
 {id:'payment',icon:'fa-credit-card',es:'Problema con un pago o Premium',en:'Problem with a payment or Premium',msg_es:'tengo un problema con un pago o con mi Premium',msg_en:'I have a problem with a payment or my Premium'},
 {id:'dating',icon:'fa-heart',es:'Problema en Citas',en:'Problem with Dating',msg_es:'tengo un problema en la sección de Citas',msg_en:'I have a problem in the Dating section'},
 {id:'account',icon:'fa-user-gear',es:'Cuenta o número de teléfono',en:'Account or phone number',msg_es:'tengo un problema con mi cuenta o mi número de teléfono',msg_en:'I have a problem with my account or phone number'},
 {id:'report',icon:'fa-flag',es:'Reportar a un usuario',en:'Report a user',msg_es:'quiero reportar a un usuario',msg_en:'I want to report a user'},
 {id:'other',icon:'fa-circle-question',es:'Otro motivo',en:'Something else',msg_es:'necesito ayuda con otra consulta',msg_en:'I need help with something else'}
];
function toast(m){const e=$('#toast');e.textContent=m;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),2300)}
function t(k){return i18n[state.language][k]||k}
function applyLanguage(){document.documentElement.lang=state.language;$$('[data-i18n]').forEach(e=>{const k=e.dataset.i18n;if(i18n[state.language][k])e.textContent=i18n[state.language][k]});$$('[data-i18n-placeholder]').forEach(e=>{const k=e.dataset.i18nPlaceholder;if(i18n[state.language][k])e.placeholder=i18n[state.language][k]});const weeklyPrice=$('.plan[data-plan="weekly"] b'),monthlyPrice=$('.plan[data-plan="monthly"] b'),annualPrice=$('.plan[data-plan="annual"] b');if(weeklyPrice)weeklyPrice.textContent=state.paymentPricing?.plans?.weekly?.amount||'2500 CUP';if(monthlyPrice)monthlyPrice.textContent=state.paymentPricing?.plans?.monthly?.amount||'7500 CUP';if(annualPrice)annualPrice.textContent=state.paymentPricing?.plans?.annual?.amount||'15500 CUP';const iphoneNote=$('[data-i18n="iphone_soon"]');if(iphoneNote)iphoneNote.textContent=state.language==='es'?'Disponible próximamente':'Coming soon';$('#languageValue').textContent=state.language==='es'?'Español':'English';renderModes();updateUsage();}
async function loadPaymentPricing(){try{const r=await fetch('/api/payments/pricing');if(!r.ok)return;state.paymentPricing=await r.json();const w=$('.plan[data-plan="weekly"] b'),m=$('.plan[data-plan="monthly"] b'),a=$('.plan[data-plan="annual"] b');if(w)w.textContent=state.paymentPricing?.plans?.weekly?.amount||w.textContent;if(m)m.textContent=state.paymentPricing?.plans?.monthly?.amount||m.textContent;if(a)a.textContent=state.paymentPricing?.plans?.annual?.amount||a.textContent}catch(_){/* Keep safe server-matching fallback labels. */}}
function setModule(m){state.module=m;$$('.segment').forEach(b=>b.classList.toggle('active',b.dataset.module===m));$('#chatScreen').classList.toggle('hidden',m!=='chat');$('#storyScreen').classList.toggle('hidden',m!=='story');renderModes()}
function renderModes(){const box=state.module==='chat'?$('#chatModes'):$('#storyModes');box.innerHTML='';modes[state.module].forEach(([key,icon,locked])=>{const b=document.createElement('button');b.className='mode-card'+(key===state.mode?' selected':'')+(locked?' locked':'')+(locked&&state.premium?' premium-unlocked':'');b.dataset.mode=key;b.innerHTML=`<span class="mode-icon"><i class="fa-solid ${icon}"></i></span><strong>${labels[state.language][key]}</strong>${locked&&!state.premium?'<span class="lock">🔒</span>':''}`;b.onclick=()=>{if(locked&&!state.premium){showPremium('locked');return}state.mode=key;renderModes()};box.appendChild(b)})}
function usageText(){return state.premium?(state.language==='es'?'Premium activo · sin límite':'Premium active · unlimited'):(state.remaining===0?t('no_more'):`${state.remaining} ${state.language==='es'?'análisis restantes hoy':'analyses left today'}`)}
function updateUsage(){['#usageText','#storyUsageText'].forEach(s=>{if($(s))$(s).textContent=usageText()});$$('.limit-warning').forEach(e=>e.classList.toggle('hidden',state.premium||state.remaining>0))}
const _fetch=(window.fetch||fetch).bind(window);
window.fetch=async function(url,options={}){options={...options,headers:{...(options.headers||{})}};if(state.authToken&&((String(url).startsWith("/api/")&&!String(url).startsWith("/api/auth/"))||String(url)==="/ocr"))options.headers.Authorization="Bearer "+state.authToken;return _fetch(url,options)};

async function auth(){try{const r=await fetch('/api/auth/telegram',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initData:tg?.initData||'',user_id:state.userId})});if(!r.ok)throw 0;const d=await r.json();state.userId=String(d.user_id);state.authToken=String(d.token||"");if(state.authToken)sessionStorage.setItem('liggacuba_auth',state.authToken);checkAdminShortcut();window.warmDating?.();state.premium=!!d.premium;state.remaining=Number(d.remaining||0);loadProfile();updateUsage()}catch(e){refreshUsage()}}
async function checkAdminShortcut(){try{const r=await fetch('/api/admin/telegram-access',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId})});if(!r.ok)throw new Error('No autorizado');const d=await r.json();$('#adminShortcut')?.classList.toggle('hidden',!d.allowed);if(d.allowed&&$('#adminShortcut'))$('#adminShortcut').setAttribute('href',d.url||'/admin.html')}catch(e){$('#adminShortcut')?.classList.add('hidden')}}
async function refreshUsage(){try{const r=await fetch('/api/usage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Error');state.premium=!!d.premium;state.remaining=Number(d.remaining||0);updateUsage()}catch(e){toast(e.message)}}
function openFile(input){const f=input.files?.[0];if(!f)return;if(f.size>8*1024*1024){toast(state.language==='es'?'Máximo 8 MB':'Maximum 8 MB');input.value='';return}openCropper(f)}
let crop={file:null,img:null,box:{x:.08,y:.08,w:.84,h:.84},drag:false,resize:null,sx:0,sy:0,start:null};
function openCropper(file){crop.file=file;crop.img=$('#cropImage');crop.img.onload=()=>{$('#cropModal').classList.remove('hidden');syncCrop()};crop.img.src=URL.createObjectURL(file)}
function imageRect(){const v=$('#cropViewport').getBoundingClientRect(),i=$('#cropImage').getBoundingClientRect();return {x:i.left-v.left,y:i.top-v.top,w:i.width,h:i.height,vw:v.width,vh:v.height}}
function syncCrop(){const v=$('#cropViewport').getBoundingClientRect(),r=imageRect(),b=$('#cropBox');if(!v.width||!r.w)return;b.style.left=((r.x+crop.box.x*r.w)/v.width*100)+'%';b.style.top=((r.y+crop.box.y*r.h)/v.height*100)+'%';b.style.width=(crop.box.w*r.w/v.width*100)+'%';b.style.height=(crop.box.h*r.h/v.height*100)+'%'}
function closeCrop(){if(crop.img?.src)URL.revokeObjectURL(crop.img.src);crop.file=null;crop.img=null;$('#cropImage').src='';$('#cropModal').classList.add('hidden')}
function pointerImagePos(ev){const r=imageRect();return{x:Math.max(0,Math.min(1,(ev.clientX-$('#cropViewport').getBoundingClientRect().left-r.x)/r.w)),y:Math.max(0,Math.min(1,(ev.clientY-$('#cropViewport').getBoundingClientRect().top-r.y)/r.h))}}
function beginCrop(ev){ev.preventDefault();const p=pointerImagePos(ev),b=crop.box,hs=.055;let resize=null;if(Math.abs(p.x-b.x)<hs&&Math.abs(p.y-b.y)<hs)resize='tl';else if(Math.abs(p.x-(b.x+b.w))<hs&&Math.abs(p.y-b.y)<hs)resize='tr';else if(Math.abs(p.x-b.x)<hs&&Math.abs(p.y-(b.y+b.h))<hs)resize='bl';else if(Math.abs(p.x-(b.x+b.w))<hs&&Math.abs(p.y-(b.y+b.h))<hs)resize='br';crop.drag=!resize;crop.resize=resize;crop.sx=p.x;crop.sy=p.y;crop.start={...b}}
function moveCrop(ev){if(!crop.drag&&!crop.resize)return;const p=pointerImagePos(ev),s=crop.start,b={...s},min=.12,dx=p.x-crop.sx,dy=p.y-crop.sy;if(crop.drag){b.x=Math.max(0,Math.min(1-b.w,s.x+dx));b.y=Math.max(0,Math.min(1-b.h,s.y+dy))}else if(crop.resize==='tl'){const nx=Math.min(s.x+s.w-min,p.x),ny=Math.min(s.y+s.h-min,p.y);b.x=Math.max(0,nx);b.y=Math.max(0,ny);b.w=s.x+s.w-b.x;b.h=s.y+s.h-b.y}else if(crop.resize==='tr'){b.y=Math.max(0,Math.min(s.y+s.h-min,p.y));b.w=Math.max(min,Math.min(1-s.x,p.x-s.x));b.h=s.y+s.h-b.y}else if(crop.resize==='bl'){b.x=Math.max(0,Math.min(s.x+s.w-min,p.x));b.w=s.x+s.w-b.x;b.h=Math.max(min,Math.min(1-s.y,p.y-s.y))}else{b.w=Math.max(min,Math.min(1-s.x,p.x-s.x));b.h=Math.max(min,Math.min(1-s.y,p.y-s.y))}crop.box=b;syncCrop()}
function endCrop(){crop.drag=false;crop.resize=null}
async function useCrop(){if(!crop.file)return;try{const img=crop.img,r=imageRect(),s=crop.box;const sx=Math.round(img.naturalWidth*s.x),sy=Math.round(img.naturalHeight*s.y),sw=Math.max(1,Math.round(img.naturalWidth*s.w)),sh=Math.max(1,Math.round(img.naturalHeight*s.h));const c=document.createElement('canvas'),scale=Math.min(2.2,2200/Math.max(sw,sh));c.width=Math.min(2400,Math.max(1,Math.round(sw*scale)));c.height=Math.min(2400,Math.max(1,Math.round(sh*scale)));c.getContext('2d').drawImage(img,sx,sy,sw,sh,0,0,c.width,c.height);const blob=await new Promise(r=>c.toBlob(r,'image/jpeg',.95));state.file=new File([blob],`liggacuba-${Date.now()}.jpg`,{type:'image/jpeg'});setPreview(state.file);closeCrop();toast(state.language==='es'?'Captura ajustada':'Screenshot adjusted')}catch(e){toast(state.language==='es'?'No se pudo recortar':'Crop failed')}}
function setPreview(file){const u=URL.createObjectURL(file);if(state.module==='chat'){$('#emptyUpload').classList.add('hidden');$('#imagePreview').classList.remove('hidden');$('#previewImg').src=u}else{$('#storyEmpty').classList.add('hidden');$('#storyPreview').classList.remove('hidden');$('#storyPreviewImg').src=u}}
function clearImage(){state.file=null;if(state.module==='chat'){$('#emptyUpload').classList.remove('hidden');$('#imagePreview').classList.add('hidden');$('#imageInput').value=''}else{$('#storyEmpty').classList.remove('hidden');$('#storyPreview').classList.add('hidden');$('#storyInput').value=''}}
async function runOCR(file){const r=await fetch('/ocr',{method:'POST',headers:{'Content-Type':file.type||'image/jpeg'},body:await file.arrayBuffer()});const d=await r.json();if(!r.ok)throw new Error(d.detail||'OCR error');return d.text||''}
async function consume(image=''){const r=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId,mode:state.mode,module:state.module,image})});const d=await r.json();if(r.status===403){state.remaining=0;updateUsage();showPremium('limit');throw new Error('__PREMIUM__')}if(r.status===402){showPremium('locked');throw new Error('__PREMIUM__')}if(!r.ok)throw new Error(d.detail||'No se pudo validar el límite');state.premium=!!d.premium;state.remaining=Number(d.remaining||0);state.lastAnalysisId=d.analysis_id||null;updateUsage();return d}
async function analyze(){if(state._analyzing)return;state._analyzing=true;state.lastGenerationKey=null;state.lastAnalysisId=null;state.lastAnalysisImage=null;if(!state.file)return toast(state.language==='es'?'Agrega una imagen primero':'Add an image first');if(!state.premium&&state.remaining<=0)return showPremium('limit');const moduleAtStart=state.module,btn=moduleAtStart==='chat'?$('#analyzeButton'):$('#storyAnalyze');btn.disabled=true;const original=btn.innerHTML;btn.classList.add('is-loading');let progress=null;let adSession=null;try{const steps=moduleAtStart==='chat'?['Preparando la captura…','Analizando la conversación…','Preparando respuestas…']:['Preparando la historia o estado…','Analizando el contenido visual…','Preparando respuestas…'];let step=0;btn.innerHTML=`<span class="analysis-progress">🔍 ${steps[step]}</span>`;progress=setInterval(()=>{step=Math.min(step+1,steps.length-1);btn.innerHTML=`<span class="analysis-progress">${step===steps.length-1?'💜':'🔍'} ${steps[step]}</span>`},900);adSession=window.LCAds?window.LCAds.start():null;const imageData=await compressedImageDataUrl(state.file);const analysis=await consume(imageData);state.lastAnalysisId=analysis.analysis_id||null;state.analysisModule=moduleAtStart;state.analysisMode=state.mode;state.lastAnalysisText='';state.lastAnalysisImage=imageData;state.retryUsed=false;btn.innerHTML=`<span class="analysis-progress">🧠 Generando respuestas…</span>`;const reply1=await generate('',imageData);const reply2=state.lastReply2||makeAlternative(reply1);state.lastReply1=reply1;$('#resultCapture').src=imageData;$('#resultCapture').alt=state.language==='es'?'Captura original seleccionada':'Original selected screenshot';$('#retryAnswerBlock1').classList.add('hidden');$('#retryAnswerBlock2').classList.add('hidden');$('#retryReplyOutput1').textContent='—';$('#retryReplyOutput2').textContent='—';$('#replyOutput').textContent=reply1||'—';$('#replyOutput2').textContent=reply2||'—';$('#providerOutput').textContent=state.lastProvider||'Proveedor no informado';$('#providerOutput2').textContent=state.lastProvider||'Proveedor no informado';$('#retryAnalysis').disabled=false;$('#retryAnalysis').textContent='🔄 Reintentar';$('#copyStatus').textContent='';if(adSession)await adSession.finish();$('#resultModal').classList.remove('hidden');}catch(e){if(adSession)adSession.cancel();if(state.lastAnalysisId){try{await fetch('/api/analyze/release',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_id:state.lastAnalysisId,text:''})})}catch(_){}}if(e.message!=='__PREMIUM__')toast(e.message||'Error')}finally{if(progress)clearInterval(progress);btn.disabled=false;btn.classList.remove('is-loading');btn.innerHTML=original;state._analyzing=false;}}
function makeAlternative(reply){let r=String(reply||'').trim();if(!r)return 'Puedes responder de forma natural y mantener la conversación abierta 🙂.';const replacements=[['Puedes responder con humor:','Otra opción, con humor:'],['Puedes responder con cercanía:','También podrías decir:'],['Puedes responder de forma segura:','Una alternativa más tranquila:'],['Puedes responder:','Otra forma de responder:'],['Para salir bien de la situación, puedes responder:','Otra manera de aclararlo sería:']];for(const [a,b] of replacements){if(r.startsWith(a))return b+r.slice(a.length)}return 'Otra alternativa: '+r.replace(/^Puedes /,'Podrías ')}
async function compressedImageDataUrl(file,maxSide=1600,quality=0.82){
  // Reduce el peso antes de subir: una captura de iPhone puede pesar varios MB y la subida se corta en conexiones lentas.
  const original=await imageAsDataUrl(file);
  try{
    if(!file||!/^image\/(png|jpeg|jpg|webp)$/i.test(file.type||'')||file.size<350*1024)return original;
    const url=URL.createObjectURL(file);
    const img=await new Promise((res,rej)=>{const i=new Image();i.onload=()=>res(i);i.onerror=()=>rej(new Error('img'));i.src=url});
    URL.revokeObjectURL(url);
    const scale=Math.min(1,maxSide/Math.max(img.naturalWidth,img.naturalHeight));
    const w=Math.max(1,Math.round(img.naturalWidth*scale)),h=Math.max(1,Math.round(img.naturalHeight*scale));
    const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);ctx.drawImage(img,0,0,w,h);
    const out=canvas.toDataURL('image/jpeg',quality);
    return out&&out.startsWith('data:image/jpeg')&&out.length<original.length?out:original;
  }catch(_){return original}
}
async function imageAsDataUrl(file){if(!file)return '';return await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(typeof reader.result==='string'?reader.result:'');reader.onerror=()=>reject(new Error('No se pudo leer la imagen para el análisis visual'));reader.readAsDataURL(file)})}
async function generate(text,imageFile=state.lastAnalysisImage){
  const image=typeof imageFile==='string'&&imageFile.startsWith('data:')?imageFile:await imageAsDataUrl(imageFile);
  if(!state.lastGenerationKey)state.lastGenerationKey=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(16).slice(2));
  const body=JSON.stringify({user_id:state.userId,mode:state.analysisMode||state.mode,module:state.analysisModule||state.module,text,analysis_id:state.lastAnalysisId,image,idempotency_key:state.lastGenerationKey});
  let r,d,lastError;
  // If the response is lost after the server commits, replay the same idempotency key to fetch the saved result.
  for(let attempt=0;attempt<3;attempt++){
    try{
      r=await fetch('/api/generate-reply',{method:'POST',headers:{'Content-Type':'application/json'},body});
      d=await r.json();
      if(r.status===409&&/procesando|en curso/i.test(String(d.detail||''))&&attempt<2){await new Promise(resolve=>setTimeout(resolve,700*(attempt+1)));continue;}
      break;
    }catch(error){lastError=error;if(attempt<2){await new Promise(resolve=>setTimeout(resolve,400*(attempt+1)));continue;}throw new Error('Se perdió la conexión al recibir la respuesta. Puedes volver a intentarlo sin generar otra operación.');}
  }
  if(!r||!r.ok)throw new Error((d&&d.detail)||'Error');
  state.lastGenerationKey=null;state.lastReply2=typeof d.alternative==='string'?d.alternative:'';state.lastProvider=typeof d.provider==='string'?d.provider:'desconocido';state.lastOCRText=typeof d.ocr_text==='string'?d.ocr_text:'';return d.reply
}
const screenStack=[];
const TOP_SCREENS=['homeScreen','datingScreen','profileScreen','settingsScreen','moreScreen','paymentMethodScreen','transferScreen','proofScreen','supportScreen','premiumScreen','businessAdScreen','businessAdEditorScreen'];
const FULL_SCREENS=['premiumScreen','transferScreen','paymentMethodScreen','proofScreen','supportScreen','businessAdScreen','businessAdEditorScreen'];
// Pantalla principal visible. No usar $$('.screen').find(): chatScreen y storyScreen viven dentro de homeScreen y siempre
// aparecen "visibles", lo que dejaba la pila de navegación con 'chatScreen' y la pantalla en blanco al volver atrás.
function currentScreenId(){return TOP_SCREENS.find(id=>{const e=$('#'+id);return e&&!e.classList.contains('hidden')})||'homeScreen'}
function hideTopScreens(){TOP_SCREENS.forEach(id=>$('#'+id)?.classList.add('hidden'))}
function showScreen(id){const cur=currentScreenId();if(cur!==id){screenStack.push(cur);if(screenStack.length>20)screenStack.splice(0,screenStack.length-20);}hideTopScreens();$('#'+id)?.classList.remove('hidden');$('.bottom-nav').classList.toggle('hidden',FULL_SCREENS.includes(id));}
function goBack(){const previous=screenStack.pop();if(!previous)return home();if(previous==='homeScreen')return home();if(previous==='profileScreen')return profile();if(previous==='settingsScreen')return settings();if(previous==='moreScreen')return more();if(previous==='statsScreen')return showStats();hideTopScreens();$('#'+previous)?.classList.remove('hidden');$('.bottom-nav').classList.toggle('hidden',FULL_SCREENS.includes(previous));}
function showPremium(reason='general'){try{window.LiggaChat&&window.LiggaChat.leaveDating&&window.LiggaChat.leaveDating()}catch(_){};const cur=currentScreenId();if(cur!=='premiumScreen'){screenStack.push(cur);if(screenStack.length>20)screenStack.splice(0,screenStack.length-20);}['#datingScreen','#homeScreen','#profileScreen','#settingsScreen','#moreScreen','#transferScreen','#paymentMethodScreen','#proofScreen','#supportScreen','#businessAdScreen','#businessAdEditorScreen'].forEach(s=>$(s)?.classList.add('hidden'));$('#premiumScreen').classList.remove('hidden');$('.bottom-nav').classList.add('hidden');if(reason==='limit')$('#premiumReason').textContent=t('no_more');else if(reason==='locked')$('#premiumReason').textContent=t('premium_only');else $('#premiumReason').textContent='';updatePremiumView()}
function hidePremium(){['#premiumScreen','#paymentFlow','#transferScreen','#paymentMethodScreen','#proofScreen','#supportScreen','#businessAdScreen','#businessAdEditorScreen'].forEach(s=>$(s)?.classList.add('hidden'));goBack()}
function updatePremiumView(){const active=state.premium;$('#premiumActive').classList.toggle('hidden',!active);$('#premiumPlans').classList.toggle('hidden',active);if(active){$('#premiumUntil').textContent=state.premiumUntil?formatCubaDate(state.premiumUntil):'—'}}
function showPaymentMethods(skipCurrentProfile=false){const cur=currentScreenId();if(cur!=='paymentMethodScreen'&&!(skipCurrentProfile===true&&cur==='profileScreen')){screenStack.push(cur);if(screenStack.length>20)screenStack.splice(0,screenStack.length-20);}hideTopScreens();$('#paymentMethodScreen').classList.remove('hidden');$('.bottom-nav').classList.add('hidden');}
function stopPaymentPolling(){if(state.paymentTimer){clearInterval(state.paymentTimer);state.paymentTimer=null}}
function hideProofEntry(){$('#proofEntry')?.classList.add('hidden');$('#proofSubmission')?.classList.add('hidden')}
function showProofEntry(){$('#proofEntry')?.classList.remove('hidden');$('#proofSubmission')?.classList.remove('hidden');if($('#paymentProofFile'))$('#paymentProofFile').value='';if($('#paymentProofText'))$('#paymentProofText').value='';if($('#proofFileName'))$('#proofFileName').textContent=state.language==='es'?'Opcional · JPG/PNG':'Optional · JPG/PNG'}
function methodName(m){return m==='SALDO_MOVIL'?(state.language==='es'?'Saldo móvil':'Mobile balance'):m}
// Pide el crear/recuperar la operación. Devuelve null si hubo que redirigir al perfil (falta el teléfono).
async function requestPending(method){
  const r=await fetch('/api/payments/pending',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId,plan:state.plan,language:state.language,payment_method:method})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){
    const detail=String(d.detail||'');
    if(r.status===400&&detail.includes('Configura tu número de teléfono en Perfil')){
      state.pendingPaymentMethod=method;
      toast(state.language==='es'?'Configura tu número de teléfono en Perfil antes de continuar.':'Add your phone number in Profile before continuing.');
      profile();return null;
    }
    throw new Error(detail||'Error');
  }
  return d;
}
// Aviso con dos opciones. Devuelve 'resume', 'new' o null (si se cierra tocando fuera).
function askActivePayment(d){
  return new Promise(resolve=>{
    const modal=$('#activePaymentModal');
    $('#activePaymentText').textContent=(state.language==='es'
      ?`Operación ${d.operation_id} · ${methodName(d.payment_method)} · ${d.amount}. Puedes retomarla o borrarla para crear una nueva.`
      :`Operation ${d.operation_id} · ${methodName(d.payment_method)} · ${d.amount}. You can resume it or delete it to create a new one.`);
    const done=v=>{modal.classList.add('hidden');$('#resumePayment').onclick=null;$('#replacePayment').onclick=null;modal.querySelector('.crop-backdrop').onclick=null;resolve(v)};
    $('#resumePayment').onclick=()=>done('resume');
    $('#replacePayment').onclick=()=>done('new');
    modal.querySelector('.crop-backdrop').onclick=()=>done(null);
    modal.classList.remove('hidden');
  });
}
async function createPayment(){
  const btn=$('#continuePaymentMethod');if(btn)btn.disabled=true;
  try{
    const method=state.paymentMethod||'BANDEC';
    let d=await requestPending(method);
    if(!d)return;
    if(d.existing_operation){
      const choice=await askActivePayment(d);
      if(choice===null)return;
      if(choice==='new'){
        const r=await fetch('/api/payments/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation_id:d.operation_id,user_id:state.userId})});
        const c=await r.json().catch(()=>({}));
        if(!r.ok)throw new Error(c.detail||'Error');
        stopPaymentPolling();state.operationId=null;
        d=await requestPending(method);
        if(!d)return;
        if(d.existing_operation)throw new Error(state.language==='es'?'No se pudo crear la nueva operación. Inténtalo de nuevo.':'Could not create the new operation. Try again.');
      }
    }
    showOperation(d);
  }catch(e){toast(e.message)}
  finally{if(btn)btn.disabled=false}
}
function showOperation(d){
  state.operationId=d.operation_id;
  $('#cancelPayment')?.classList.remove('hidden');$('#restartPayment')?.classList.add('hidden');showProofEntry();
  const actualMethod=d.payment_method||state.paymentMethod||'BANDEC';
  if(['BANDEC','BPA','SALDO_MOVIL'].includes(actualMethod))state.paymentMethod=actualMethod;
  $$('.payment-method[data-method]').forEach(b=>b.classList.toggle('selected',b.dataset.method===state.paymentMethod));
  state.paymentPhone=d.payment_phone||state.paymentPhone||'';
  $('#paymentStatus').textContent=(state.language==='es'?'Operación ':'Operation ')+d.operation_id+' · '+d.amount;
  $('#paymentMethodLabel').textContent=methodName(state.paymentMethod);
  $('#paymentAmount').textContent=d.amount;
  $('#paymentDestination').textContent=state.paymentMethod==='SALDO_MOVIL'?'52677163':(d.destination_account||'').replace(/(\d{4})(?=\d)/g,'$1 ');
  $('#paymentConfirmNumberRow').classList.toggle('hidden',!['BANDEC','BPA'].includes(state.paymentMethod));
  $('#paymentFlow').classList.remove('hidden');
  $('#startPayment').classList.add('hidden');
  const transferScreen=$('#transferScreen');
  if(transferScreen&&$('#paymentFlow').parentElement!==transferScreen)transferScreen.appendChild($('#paymentFlow'));
  hideTopScreens();
  $('#transferScreen').classList.remove('hidden');
  $('.bottom-nav').classList.add('hidden');
  if(screenStack[screenStack.length-1]!=='paymentMethodScreen')screenStack.push('paymentMethodScreen');
  startPaymentStatusPolling();
}

async function submitProof(){
  if(!state.operationId)return toast(state.language==='es'?'Primero crea una operación de pago':'Create a payment operation first');
  const file=$('#paymentProofFile')?.files?.[0];
  const proofText=String($('#paymentProofText')?.value||'').trim();
  if(!file&&!proofText)return toast(state.language==='es'?'Adjunta una imagen o escribe los datos del pago':'Attach an image or enter payment details');
  if(file&&file.size>2_100_000)return toast(state.language==='es'?'La imagen debe pesar menos de 2.1 MB':'Image must be smaller than 2.1 MB');
  const button=$('#submitProof');if(button)button.disabled=true;
  try{
    const proofImage=file?await imageAsDataUrl(file):'';
    const r=await fetch('/api/payments/proof',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation_id:state.operationId,user_id:state.userId,proof_text:proofText,proof_image:proofImage})});
    const d=await r.json().catch(()=>({detail:'Respuesta inválida'}));
    if(!r.ok)throw new Error(d.detail||'No se pudo enviar el comprobante');
    $('#paymentStatus').textContent=state.language==='es'?'Comprobante enviado. Pendiente de revisión administrativa.':'Proof submitted. Waiting for administrator review.';
    hideProofEntry();
    if(currentScreenId()==='proofScreen')goBack();
    toast(state.language==='es'?'Comprobante enviado':'Proof submitted');
    startPaymentStatusPolling();
  }catch(e){toast(e.message||'Error al enviar el comprobante')}
  finally{if(button)button.disabled=false}
}
async function pollPayment(){
  if(!state.operationId)return;
  try{
    const r=await fetch('/api/payments/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation_id:state.operationId,user_id:state.userId})});
    if(!r.ok)return;const d=await r.json();
    if(d.status==='verified'){
      if(String(d.plan||'').startsWith('ad_')){
        $('#paymentStatus').textContent=state.language==='es'?'Plan de anuncio activado. Ya puedes editar tu anuncio desde Más → Anunciar mi negocio.':'Ad plan activated. You can now edit your ad from More → Advertise my business.';
        hideProofEntry();$('#cancelPayment')?.classList.add('hidden');
        if(state.paymentTimer){clearInterval(state.paymentTimer);state.paymentTimer=null}
        return;
      }
      state.premium=true;state.premiumUntil=d.premium_until||null;
      $('#paymentStatus').textContent=state.language==='es'?'Premium activado.':'Premium activated.';
      hideProofEntry();$('#cancelPayment')?.classList.add('hidden');
      if(state.paymentTimer){clearInterval(state.paymentTimer);state.paymentTimer=null}
      updatePremiumView();refreshUsage();
    }else if(d.status==='proof_submitted'){
      $('#paymentStatus').textContent=state.language==='es'?'Comprobante enviado. Pendiente de revisión administrativa.':'Proof submitted. Waiting for administrator review.';
      hideProofEntry();
    }else if(d.status==='rejected'){
      $('#paymentStatus').textContent=state.language==='es'?'Pago rechazado. Puedes iniciar una nueva operación.':'Payment rejected. You can start a new operation.';
      hideProofEntry();$('#cancelPayment')?.classList.add('hidden');$('#restartPayment')?.classList.remove('hidden');
      if(state.paymentTimer){clearInterval(state.paymentTimer);state.paymentTimer=null}
    }else if(d.status==='cancelled'){
      $('#paymentStatus').textContent=state.language==='es'?'Operación cancelada.':'Operation cancelled.';
      hideProofEntry();$('#cancelPayment')?.classList.add('hidden');$('#restartPayment')?.classList.remove('hidden');
      if(state.paymentTimer){clearInterval(state.paymentTimer);state.paymentTimer=null}
    }
  }catch(_){/* Temporary network errors are retried on the next poll. */}
}
function startPaymentStatusPolling(){if(state.paymentTimer)clearInterval(state.paymentTimer);pollPayment();state.paymentTimer=setInterval(pollPayment,10000)}
async function cancelPayment(){if(!state.operationId)return;const r=await fetch('/api/payments/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation_id:state.operationId,user_id:state.userId})});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Error');stopPaymentPolling();state.operationId=null;$('#paymentStatus').textContent=state.language==='es'?'Operación cancelada.':'Operation cancelled.';$('#startPayment').classList.remove('hidden');$('#paymentFlow').classList.add('hidden');$('#transferScreen').classList.add('hidden');$('#premiumScreen').classList.add('hidden');$('#paymentMethodScreen').classList.remove('hidden');if(screenStack[screenStack.length-1]==='paymentMethodScreen')screenStack.pop();$('.bottom-nav').classList.add('hidden');toast(state.language==='es'?'Operación cancelada':'Operation cancelled')}
function setPhoneUI(phone,editing=false){
  const has=!!phone;
  state.paymentPhone=phone||'';
  $('#phoneSaved').classList.toggle('hidden',!has||editing);
  $('#phoneEdit').classList.toggle('hidden',has&&!editing);
  $('#cancelPhoneEdit').classList.toggle('hidden',!(has&&editing));
  $('#phoneSavedValue').textContent=has?'+53 '+phone:'—';
  $('#profilePhone').value=editing||!has?(has&&editing?phone:''):'';
}
function askConfirm(message){
  return new Promise(resolve=>{
    if(tg?.showConfirm){try{return tg.showConfirm(message,ok=>resolve(!!ok))}catch(_){}}
    resolve(window.confirm(message));
  });
}
async function deletePhone(){
  if(!await askConfirm(t('phone_delete_confirm')))return;
  try{
    const r=await fetch('/api/payment-phone/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.detail||'Error');
    setPhoneUI('');toast(t('phone_deleted'));
  }catch(e){toast(e.message||'Error')}
}
async function savePhone(input){try{const phone=String(input?.value||'').trim();const r=await fetch('/api/payment-phone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone})});const d=await r.json().catch(()=>({detail:'Respuesta inválida'}));if(!r.ok)throw new Error(d.detail||'No se pudo guardar el teléfono');state.paymentPhone=d.payment_phone||phone;setPhoneUI(state.paymentPhone);toast(state.language==='es'?'Número guardado correctamente':'Phone number saved');if(state.pendingPaymentMethod){state.paymentMethod=state.pendingPaymentMethod;state.pendingPaymentMethod=null;$$('.payment-method[data-method]').forEach(b=>b.classList.toggle('selected',b.dataset.method===state.paymentMethod));showPaymentMethods(true)}return true}catch(e){toast(e.message||'Error al guardar el número');return false}}
async function loadProfile(){try{const r=await fetch('/api/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId})});const d=await r.json();if(!r.ok)return;$('#profileName').textContent=d.first_name||d.username||'LiggaCuba';$('#profileUsername').textContent=d.username?`@${d.username}`:'LiggaCuba';$('#statChats').textContent=d.chats||0;$('#statStories').textContent=d.stories||0;$('#statAnalyses').textContent=d.analyses||0;setPhoneUI(d.payment_phone||'');$('#profileBenefits').classList.toggle('hidden',!d.premium);state.premium=!!d.premium;state.premiumUntil=d.premium_until||null;$('#profilePlan').textContent=state.premium?t('premium_active'):t('free_plan');$('#profilePlanHelp').textContent=state.premium&&state.premiumUntil?`${t('premium_until')}: ${formatCubaDate(state.premiumUntil)} · ${Math.max(0,Math.ceil((new Date(state.premiumUntil)-Date.now())/86400000))} ${state.language==='es'?'días restantes':'days left'}`:t('free_help');$('#profilePremiumButton').textContent=state.premium?t('premium_active'):t('go_premium');updatePremiumView()}catch(e){}}
function profile(){try{window.LiggaChat&&window.LiggaChat.leaveDating&&window.LiggaChat.leaveDating()}catch(_){}['#datingScreen','#homeScreen','#settingsScreen','#premiumScreen','#moreScreen','#transferScreen','#paymentMethodScreen','#proofScreen','#supportScreen','#businessAdScreen','#businessAdEditorScreen'].forEach(s=>$(s)?.classList.add('hidden'));$('#profileScreen').classList.remove('hidden');$('.bottom-nav').classList.remove('hidden');$$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.nav==='profile'));loadProfile()}
function home(){try{window.LiggaChat&&window.LiggaChat.leaveDating&&window.LiggaChat.leaveDating()}catch(_){}['#datingScreen','#profileScreen','#settingsScreen','#premiumScreen','#moreScreen','#transferScreen','#paymentMethodScreen','#proofScreen','#supportScreen','#businessAdScreen','#businessAdEditorScreen'].forEach(s=>$(s)?.classList.add('hidden'));$('#homeScreen').classList.remove('hidden');$('.bottom-nav').classList.remove('hidden');$$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.nav==='home'));setModule(state.module)}
function settings(){try{window.LiggaChat&&window.LiggaChat.leaveDating&&window.LiggaChat.leaveDating()}catch(_){}['#datingScreen','#homeScreen','#profileScreen','#premiumScreen','#moreScreen','#transferScreen','#paymentMethodScreen','#proofScreen','#supportScreen','#businessAdScreen','#businessAdEditorScreen'].forEach(s=>$(s)?.classList.add('hidden'));$('#settingsScreen').classList.remove('hidden');$('.bottom-nav').classList.remove('hidden');}
async function showStats(){
  ['#homeScreen','#profileScreen','#settingsScreen','#premiumScreen','#moreScreen','#datingScreen','#supportScreen'].forEach(s=>$(s)?.classList.add('hidden'));
  $('#statsScreen').classList.remove('hidden');
  $('#statsContent').innerHTML='<div class="stats-loading"><i class="fa-solid fa-spinner fa-spin"></i></div>';
  try{
    const r=await fetch('/api/stats',{headers:{'Authorization':'Bearer '+state.authToken}});
    if(!r.ok)throw new Error('Error');
    const d=await r.json();
    const lang=state.language;
    const modeEmoji={coquetear:'😏',gracioso:'😂',provocativo:'🔥',salvar:'🆘',enamorar:'💕',reactivar:'🔄'};
    const modeLabels={coquetear:'Coquetear',gracioso:'Gracioso',provocativo:'Provocativo',salvar:'Salvar situación',enamorar:'Enamorar',reactivar:'Reactivar'};
    const modesHtml=Object.entries(d.by_mode||{}).sort((a,b)=>b[1]-a[1]).map(([m,n])=>`<div class="stat-mode-row"><span>${modeEmoji[m]||'•'} ${modeLabels[m]||m}</span><b>${n}</b></div>`).join('');
    const actHtml=(d.daily_activity||[]).map(x=>`<div class="day-bar" title="${x.day}: ${x.count}"><div class="day-bar-fill" style="height:${Math.round(x.count/Math.max(...(d.daily_activity||[{count:1}]).map(a=>a.count))*60)}px"></div><span>${x.day.slice(5)}</span></div>`).join('');
    $('#statsContent').innerHTML=`
      <div class="stats-cards">
        <div class="stat-card"><span>${lang==='es'?'Esta semana':'This week'}</span><b>${d.this_week||0}</b></div>
        <div class="stat-card"><span>${lang==='es'?'Total análisis':'Total analyses'}</span><b>${d.total_analyses||0}</b></div>
        <div class="stat-card"><span>${lang==='es'?'Mejor modo':'Best mode'}</span><b>${modeEmoji[d.best_mode]||'—'} ${modeLabels[d.best_mode]||'—'}</b></div>
      </div>
      ${actHtml?`<div class="day-bars-wrap">${actHtml}</div>`:''}
      ${modesHtml?`<div class="stat-modes"><h4>${lang==='es'?'Por modo':'By mode'}</h4>${modesHtml}</div>`:''}
    `;
    $('#myReferCode').textContent=d.refer_code||'—';
    $('#referTotal').textContent=d.referrals_total||0;
    $('#referRewarded').textContent=d.referrals_rewarded||0;
  }catch(e){$('#statsContent').innerHTML='<p class="payment-note">Error cargando estadísticas</p>';}
}
function more(){try{window.LiggaChat&&window.LiggaChat.leaveDating&&window.LiggaChat.leaveDating()}catch(_){}['#datingScreen','#homeScreen','#profileScreen','#settingsScreen','#premiumScreen','#transferScreen','#paymentMethodScreen','#proofScreen','#supportScreen','#businessAdScreen','#businessAdEditorScreen','#statsScreen'].forEach(s=>$(s)?.classList.add('hidden'));$('#moreScreen').classList.remove('hidden');$('.bottom-nav').classList.remove('hidden')}
const paymentMethodsElement=$('.payment-methods');if(paymentMethodsElement&&$('#paymentMethodsHost'))$('#paymentMethodsHost').appendChild(paymentMethodsElement);
$$('.payment-method[data-method]').forEach(b=>b.onclick=async()=>{
  const next=b.dataset.method;
  if(next==='IPHONE'){
    toast(state.language==='es'?'La opción para iPhone estará disponible en futuras actualizaciones.':'The iPhone option will be available in a future update.');
    return;
  }
  try{
    const r=await fetch('/api/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId})});
    const d=await r.json();
    if(!r.ok)throw new Error(state.language==='es'?'No se pudo comprobar tu perfil.':'Could not verify your profile.');
    state.paymentPhone=String(d.payment_phone||'').trim();
    if(!state.paymentPhone){
      state.pendingPaymentMethod=next;
      profile();
      toast(t('payment_phone_required'));
      return;
    }
    state.paymentMethod=next;
    $$('.payment-method[data-method]').forEach(x=>x.classList.toggle('selected',x.dataset.method===next));
  }catch(e){
    toast(e.message||'Error');
  }
});
if($('#saveProfilePhone'))$('#saveProfilePhone').onclick=()=>savePhone($('#profilePhone'));
$('#replacePhone').onclick=()=>{setPhoneUI(state.paymentPhone,true);$('#profilePhone').focus()};
$('#cancelPhoneEdit').onclick=()=>setPhoneUI(state.paymentPhone);
$('#deletePhone').onclick=deletePhone;
state.supportReason=null;
function renderSupportReasons(){
  const box=$('#supportReasons');box.innerHTML='';
  supportReasons.forEach(r=>{
    const b=document.createElement('button');b.type='button';b.className='support-reason'+(state.supportReason===r.id?' on':'');b.setAttribute('aria-pressed',state.supportReason===r.id?'true':'false');
    b.innerHTML='<i class="fa-solid '+r.icon+'"></i><span></span><i class="fa-solid fa-circle-check tick"></i>';
    b.querySelector('span').textContent=r[state.language]||r.es;
    b.onclick=()=>{state.supportReason=r.id;renderSupportReasons()};
    box.appendChild(b);
  });
  const ready=!!state.supportReason;
  $('#supportTelegram').disabled=!ready;$('#supportWhatsapp').disabled=!ready;
  $('#supportHint').textContent=ready?t('support_ready'):t('support_pick_reason');
}
function supportMessage(){
  const r=supportReasons.find(x=>x.id===state.supportReason)||supportReasons[supportReasons.length-1];
  const es=state.language==='es';
  let msg=es?`Hola, buenas. Soy cliente de LiggaCuba y ${r.msg_es}.`:`Hi there. I'm a LiggaCuba customer and ${r.msg_en}.`;
  if(r.id==='payment'&&state.operationId)msg+=es?` Mi operación es ${state.operationId}.`:` My operation is ${state.operationId}.`;
  return msg;
}
function contactSupport(channel){
  if(!state.supportReason)return toast(t('support_pick_reason'));
  const text=encodeURIComponent(supportMessage());
  const url=channel==='telegram'?`https://t.me/pedritoficial?text=${text}`:`https://wa.me/5352677163?text=${text}`;
  try{
    if(channel==='telegram'&&tg?.openTelegramLink)return tg.openTelegramLink(url);
    if(tg?.openLink)return tg.openLink(url);
  }catch(_){}
  window.open(url,'_blank','noopener');
}
function openSupport(){state.supportReason=null;renderSupportReasons();showScreen('supportScreen')}
async function copyValue(text,message){
  try{await navigator.clipboard.writeText(String(text).replace(/\s/g,''));toast(message)}
  catch(e){toast(state.language==='es'?'No se pudo copiar':'Could not copy')}
}
$('#copyPaymentValue').onclick=()=>copyValue($('#paymentDestination').textContent,t('destination_copied')+': '+$('#paymentDestination').textContent.trim());
$('#copyConfirmNumber').onclick=()=>copyValue($('#paymentConfirmNumber').textContent,t('number_copied')+': '+$('#paymentConfirmNumber').textContent.trim());
$('#openProof').onclick=()=>showScreen('proofScreen');
$('#backFromProof').onclick=goBack;
$('#imageInput').onchange=()=>openFile($('#imageInput'));$('#storyInput').onchange=()=>openFile($('#storyInput'));$('#uploadCard').onclick=e=>{if(!e.target.closest('button'))$('#imageInput').click()};$('#storyAdd').onclick=()=>$('#storyInput').click();$('#replaceImage').onclick=()=>$('#imageInput').click();$('#storyReplace').onclick=()=>$('#storyInput').click();$('#deleteImage').onclick=clearImage;$('#storyDelete').onclick=clearImage;$('#cropCancel').onclick=closeCrop;$('#cropClose').onclick=closeCrop;$('#cropUse').onclick=useCrop;$('#cropViewport').addEventListener('pointerdown',beginCrop);window.addEventListener('pointermove',moveCrop);window.addEventListener('pointerup',endCrop);window.addEventListener('resize',syncCrop);$('#analyzeButton').onclick=analyze;$('#storyAnalyze').onclick=analyze;$('#refreshUsage').onclick=refreshUsage;$('#storyRefreshUsage').onclick=refreshUsage;$('#settingsButton').onclick=settings;$('#backFromSettings').onclick=goBack;$('#profilePremiumButton').onclick=()=>showPremium();$('#backFromPremium').onclick=goBack;$('#backFromTransfers').onclick=goBack;$('#startPayment').onclick=()=>{state.plan=$('#premiumPlans .plan.selected[data-plan]')?.dataset.plan||'weekly';showPaymentMethods()};$('#continuePaymentMethod').onclick=createPayment;$('#backFromPaymentMethods').onclick=goBack;$('#restartPayment').onclick=()=>createPayment();$('#submitProof').onclick=submitProof;$('#paymentProofFile').onchange=()=>{const f=$('#paymentProofFile').files?.[0];if($('#proofFileName'))$('#proofFileName').textContent=f?f.name:(state.language==='es'?'Opcional · JPG/PNG':'Optional · JPG/PNG')};$('#cancelPayment').onclick=()=>cancelPayment().catch(e=>toast(e.message));$('#resultClose').onclick=()=>$('#resultModal').classList.add('hidden');$('#anotherAnalysis').onclick=()=>{$('#resultModal').classList.add('hidden');clearImage()};async function copyText(text,label){try{await navigator.clipboard.writeText(text);$('#copyStatus').textContent=label+' copiada'}catch(e){toast(state.language==='es'?'No se pudo copiar':'Copy failed')}}$('#copyResponse').onclick=()=>copyText($('#replyOutput').textContent,'Respuesta #1');$('#copyAllResponse').onclick=()=>copyText($('#replyOutput').textContent,'Respuesta #1');$('#copyResponse2').onclick=()=>copyText($('#replyOutput2').textContent,'Respuesta #2');$('#copyRetryResponse1').onclick=()=>copyText($('#retryReplyOutput1').textContent,'Respuesta #3');$('#copyRetryResponse2').onclick=()=>copyText($('#retryReplyOutput2').textContent,'Respuesta #4');$('#retryAnalysis').onclick=async()=>{if(state.retryUsed)return toast('Ya utilizaste el reintento de este análisis');if(!state.lastAnalysisId||!state.lastAnalysisImage)return toast('No hay un análisis válido para reintentar');const b=$('#retryAnalysis');b.disabled=true;b.textContent='🔄 Generando…';try{const check=await fetch('/api/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_id:state.lastAnalysisId,text:state.lastAnalysisText})});const data=await check.json();if(!check.ok){state.retryUsed=true;b.textContent='Reintento no disponible';throw new Error(data.detail||'No se pudo validar el reintento')}state.retryUsed=true;state.lastGenerationKey=null;let next,next2;if(data.needs_generation===false&&Array.isArray(data.replies)&&data.replies.length>=2){next=data.replies[0];next2=data.replies[1]}else{next=await generate(state.lastAnalysisText,state.lastAnalysisImage);next2=state.lastReply2||makeAlternative(next)}$('#retryReplyOutput1').textContent=next||'—';$('#retryReplyOutput2').textContent=next2||'—';$('#retryProviderOutput1').textContent=state.lastProvider||'Proveedor no informado';$('#retryProviderOutput2').textContent=state.lastProvider||'Proveedor no informado';$('#retryAnswerBlock1').classList.remove('hidden');$('#retryAnswerBlock2').classList.remove('hidden');b.textContent='Reintento utilizado';b.disabled=true;$('#copyStatus').textContent='Se añadieron dos respuestas nuevas; las originales se conservaron.'}catch(e){state.retryUsed=true;b.disabled=true;b.textContent='Reintento utilizado';toast(e.message||'Error')}};$$('.segment').forEach(b=>b.onclick=()=>setModule(b.dataset.module));$$('.nav-item').forEach(b=>b.onclick=()=>b.dataset.nav==='profile'?profile():home());$$('.plan').forEach(b=>b.onclick=()=>{$$('.plan').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');state.plan=b.dataset.plan});$('#languageButton').onclick=()=>{state.language=state.language==='es'?'en':'es';localStorage.setItem('liggacuba_lang',state.language);applyLanguage();loadPaymentPricing();loadProfile();if(!$('#supportScreen').classList.contains('hidden'))renderSupportReasons()};$('#contactButton').onclick=openSupport;$('#supportBack').onclick=goBack;$('#supportTelegram').onclick=()=>contactSupport('telegram');$('#supportWhatsapp').onclick=()=>contactSupport('whatsapp');$('#moreButton').onclick=more;$('#moreBack').onclick=goBack;
$('#statsBack').onclick=goBack;
// Stats screen button — add to profile screen via more menu
$('#copyReferCode').onclick=async()=>{const code=$('#myReferCode').textContent;if(!code||code==='—')return;try{await navigator.clipboard.writeText(code);toast(t('refer_copied'))}catch(e){toast(code)}};
$('#applyReferCode').onclick=async()=>{const code=$('#referCodeInput').value.trim().toUpperCase();if(!code)return;const btn=$('#applyReferCode');btn.disabled=true;try{const r=await fetch('/api/referral/apply',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+state.authToken},body:JSON.stringify({refer_code:code})});const d=await r.json();const msg=$('#referApplyMsg');msg.classList.remove('hidden');msg.textContent=r.ok?t('refer_apply_ok'):d.detail||'Error';if(r.ok){$('#referCodeInput').value='';$('#referCodeInput').disabled=true;btn.style.display='none'}}catch(e){$('#referApplyMsg').classList.remove('hidden');$('#referApplyMsg').textContent='Error de conexión'}finally{btn.disabled=false}};
applyLanguage();loadPaymentPricing();const _splashTimeout=new Promise(r=>setTimeout(r,5000));Promise.race([auth(),_splashTimeout]).finally(()=>{$('#splash').classList.add('hidden');$('#app').classList.remove('hidden')});
