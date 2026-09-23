
import express from 'express';
import cors from 'cors';
import { chromium } from 'playwright';

const app = express();
app.use(cors({ origin: '*' }));
app.use(express.json());

const SITE = 'https://confirmacao-entrega-propria.ifood.com.br';

app.get('/', (req,res)=> res.send('API iFood Auto ON - POST /confirmar com {localizador, codigo}'));

app.post('/confirmar', async (req,res)=>{
  let { localizador, codigo } = req.body;
  localizador = String(localizador||'').replace(/\D/g,'').slice(0,8);
  codigo = String(codigo||'').replace(/\D/g,'').slice(0,4);
  
  if(localizador.length!==8) return res.status(400).json({ok:false, erro:'Localizador precisa 8 digitos'});
  if(codigo.length!==4) return res.status(400).json({ok:false, erro:'Codigo precisa 4 digitos'});

  let browser;
  try{
    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled']
    });
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
      viewport: { width: 390, height: 844 },
      locale: 'pt-BR'
    });
    const page = await context.newPage();
    
    // Log para debug no Render
    page.on('console', msg => console.log('PAGE:', msg.text()));

    console.log(`[IFood] Abrindo ${SITE} - loc ${localizador} cod ${codigo}`);
    await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);

    // 1. Clicar em "Cheguei no local"
    // Tenta vários seletores possíveis
    const chegueiSelectors = [
      'text=Cheguei no local',
      'text=cheguei no local',
      'button:has-text("Cheguei")',
      '[data-testid*="cheguei"]',
      'text=Cheguei'
    ];
    let clicou = false;
    for(const sel of chegueiSelectors){
      try{
        const el = page.locator(sel).first();
        if(await el.count()>0){
          await el.click({ timeout: 3000 });
          clicou = true;
          console.log(`Clicou em: ${sel}`);
          break;
        }
      }catch(e){}
    }
    await page.waitForTimeout(1500);

    // 2. Preencher Localizador (8 digitos)
    // O site tem um input - tenta achar por placeholder ou tipo
    const locInputs = [
      'input[placeholder*="localizador" i]',
      'input[inputmode="numeric"]',
      'input[type="text"]',
      'input[type="tel"]'
    ];
    let preencheuLoc = false;
    for(const sel of locInputs){
      try{
        const inputs = page.locator(sel);
        const count = await inputs.count();
        for(let i=0;i<count;i++){
          const inp = inputs.nth(i);
          if(await inp.isVisible()){
            await inp.fill('');
            await inp.fill(localizador);
            await inp.dispatchEvent('input');
            preencheuLoc = true;
            console.log(`Preencheu localizador em ${sel} idx ${i}`);
            break;
          }
        }
        if(preencheuLoc) break;
      }catch(e){}
    }
    await page.waitForTimeout(800);

    // Clicar Continuar
    try{
      const btnCont = page.locator('button:has-text("Continuar"), button:has-text("continuar"), text=Continuar').first();
      if(await btnCont.count()>0) await btnCont.click();
    }catch(e){}
    await page.waitForTimeout(2000);

    // 3. Preencher codigo 4 digitos
    let preencheuCod = false;
    // as vezes são 4 inputs separados
    const allInputs = page.locator('input');
    const nInputs = await allInputs.count();
    console.log(`Inputs encontrados na etapa codigo: ${nInputs}`);
    if(nInputs>=4){
      // tenta preencher digito a digito se forem 4 caixinhas
      const visiveis = [];
      for(let i=0;i<nInputs;i++){
        const inp = allInputs.nth(i);
        if(await inp.isVisible()){
          const val = await inp.inputValue().catch(()=> '');
          // se ja tem localizador, ignora
          if(val !== localizador) visiveis.push(inp);
        }
      }
      if(visiveis.length>=4){
        for(let k=0;k<4;k++){
          await visiveis[k].fill(codigo[k]);
        }
        preencheuCod = true;
      }
    }
    if(!preencheuCod){
      for(const sel of locInputs){
        try{
          const inputs = page.locator(sel);
          for(let i=0;i<await inputs.count();i++){
            const inp = inputs.nth(i);
            if(await inp.isVisible()){
              const v = await inp.inputValue().catch(()=> '');
              if(v.length!==8){ // não é o campo do localizador
                await inp.fill(codigo);
                preencheuCod = true;
                break;
              }
            }
          }
          if(preencheuCod) break;
        }catch(e){}
      }
    }

    await page.waitForTimeout(800);
    try{
      const btnCont2 = page.locator('button:has-text("Continuar"), button:has-text("Confirmar"), text=Confirmar').last();
      if(await btnCont2.count()>0) await btnCont2.click();
    }catch(e){}

    await page.waitForTimeout(3000);

    // Verifica se deu sucesso
    const bodyText = await page.textContent('body').catch(()=> '');
    const sucesso = /confirmad|sucesso|entrega confirmada/i.test(bodyText);
    const jaConfirmada = /já foi confirmada|já confirmada/i.test(bodyText);
    const erroCodigo = /código.*inválido|não.*encontrado|localizador.*inválido/i.test(bodyText);

    const screenshot = await page.screenshot({ type:'jpeg', quality: 70 }).catch(()=> null);
    
    await browser.close();

    if(sucesso || jaConfirmada){
      return res.json({ ok: true, status: jaConfirmada ? 'ja_confirmada' : 'confirmada', mensagem: bodyText.slice(0,500) });
    }
    if(erroCodigo){
      return res.status(422).json({ ok:false, erro:'Código ou localizador inválido', detalhe: bodyText.slice(0,600), screenshot: screenshot ? screenshot.toString('base64') : null });
    }
    return res.json({ ok: false, status: 'desconhecido', body: bodyText.slice(0,800), screenshot: screenshot ? screenshot.toString('base64') : null });

  }catch(err){
    console.error(err);
    if(browser) await browser.close().catch(()=>{});
    return res.status(500).json({ ok:false, erro: err.message });
  }
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, ()=> console.log('Rodando na porta '+PORT));
