
import os
import asyncio
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.async_api import async_playwright
import re

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

IFOOD_URL = os.getenv("IFOOD_URL", "https://confirmacao-entrega-propria.ifood.com.br")
TIMEOUT = 20000

async def confirmar_ifood(localizador: str, codigo: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"]
        )
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        )
        page = await context.new_page()
        try:
            await page.goto(IFOOD_URL, wait_until="domcontentloaded", timeout=TIMEOUT)
            await page.wait_for_timeout(2000)

            # 1) Clicar em "Cheguei no local" se existir
            for txt in ["Cheguei no local", "Cheguei no Local", "cheguei", "Já cheguei"]:
                try:
                    btn = page.get_by_text(txt, exact=False).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await page.wait_for_timeout(1500)
                        break
                except:
                    pass

            # 2) Campo localizador - tenta vários seletores
            localizador_selectors = [
                'input[placeholder*="localizador" i]',
                'input[name*="localizador" i]',
                'input[inputmode="numeric"]',
                'input[type="tel"]',
                'input[type="text"]',
            ]
            filled = False
            for sel in localizador_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=2000):
                        await loc.fill("")
                        await loc.fill(localizador)
                        filled = True
                        break
                except:
                    continue

            if not filled:
                # fallback: pega primeiro input visível
                try:
                    await page.locator("input").first.fill(localizador)
                    filled = True
                except:
                    pass

            if not filled:
                return {"success": False, "reason": "campo_localizador_nao_encontrado", "message": "Não achei campo de localizador"}

            # 3) Clicar em avançar / continuar / próximo
            for txt in ["Avançar", "Continuar", "Próximo", "Enviar", "Confirmar", "Próxima"]:
                try:
                    btn = page.get_by_text(txt, exact=False).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        break
                except:
                    continue

            await page.wait_for_timeout(2500)

            # Verifica se deu erro de localizador
            body = await page.content()
            if "inválido" in body.lower() or "não encontrado" in body.lower() or "não existe" in body.lower():
                return {"success": False, "reason": "localizador_invalido", "message": "Localizador inválido (não avançou para tela de código)."}

            # 4) Campo código 4 dígitos
            codigo_filled = False
            # tenta 4 inputs separados ou 1 único
            inputs = page.locator("input")
            count = await inputs.count()

            if count >= 4:
                # muitos sites usam 4 caixinhas
                try:
                    for i, dig in enumerate(codigo):
                        await inputs.nth(i).fill(dig)
                    codigo_filled = True
                except:
                    pass

            if not codigo_filled:
                for sel in ['input[placeholder*="código" i]', 'input[placeholder*="codigo" i]', 'input[type="tel"]', 'input[type="text"]', 'input']:
                    try:
                        c = page.locator(sel).last
                        if await c.is_visible(timeout=1000):
                            await c.fill(codigo)
                            codigo_filled = True
                            break
                    except:
                        continue

            if not codigo_filled:
                return {"success": False, "reason": "campo_codigo_nao_encontrado", "message": "Localizador ok, mas não achei campo do código."}

            await page.wait_for_timeout(1000)

            # 5) Confirmar final
            for txt in ["Confirmar entrega", "Confirmar", "Finalizar", "Concluir", "Entrega confirmada"]:
                try:
                    btn = page.get_by_text(txt, exact=False).last
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        break
                except:
                    continue

            await page.wait_for_timeout(3500)
            body_final = await page.content()
            body_lower = body_final.lower()

            if any(x in body_lower for x in ["confirmada com sucesso", "entrega confirmada", "pedido confirmado", "sucesso"]):
                return {"success": True, "plataforma": "iFood", "message": "Entrega confirmada no iFood!"}
            if "incorreto" in body_lower or "inválido" in body_lower or "código" in body_lower and "errado" in body_lower:
                return {"success": False, "reason": "codigo_invalido", "message": "Código de confirmação incorreto."}
            if "já foi confirmada" in body_lower or "já confirmada" in body_lower:
                return {"success": True, "plataforma": "iFood", "message": "Entrega já havia sido confirmada."}
            if "cancelado" in body_lower:
                return {"success": False, "reason": "pedido_cancelado", "message": "Este pedido foi cancelado."}

            # Se não detectou, retorna o HTML para debug mas considera sucesso se não tem erro visível
            return {"success": True, "plataforma": "iFood", "message": "Processo finalizado. Verifique no gestor iFood.", "debug": body_final[:2000]}

        except Exception as e:
            return {"success": False, "reason": "erro_playwright", "message": f"Erro: {str(e)}"}
        finally:
            await browser.close()

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "ifood_url": IFOOD_URL})

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "name": "ConfirmaTudo Backend - iFood",
        "endpoints": {
            "POST /confirmar-entrega": {"localizador": "8 digitos", "codigo": "4 digitos"}
        }
    })

@app.route("/confirmar-entrega", methods=["POST", "OPTIONS"])
def confirmar():
    data = request.get_json(silent=True) or {}
    localizador = str(data.get("localizador", "")).strip()
    codigo = str(data.get("codigo", "")).strip()

    if not re.fullmatch(r"\d{8}", localizador):
        return jsonify({"success": False, "reason": "formato_localizador", "message": "Localizador deve ter 8 dígitos"}), 400
    if not re.fullmatch(r"\d{4}", codigo):
        return jsonify({"success": False, "reason": "formato_codigo", "message": "Código deve ter 4 dígitos"}), 400

    result = asyncio.run(confirmar_ifood(localizador, codigo))
    status = 200 if result.get("success") else 404
    return jsonify(result), status

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
