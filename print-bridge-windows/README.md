# Ponte de impressão (Windows)

Substitui a app do tablet: corre no PC da loja e imprime os pedidos/faturas nas
impressoras instaladas no Windows.

## Instalar (uma vez)
1. Copiar a pasta `print-bridge-windows` para o PC (ex.: `C:\PrintBridge`).
2. Duplo-clique em `build.bat` → cria `PrintBridge.exe` e corre o auto-teste
   (deve dizer `SELFTEST OK`).
3. Renomear `config.example.txt` para `config.txt` e preencher:
   - `api_key`: a chave em Admin → Definições (a mesma do tablet).
   - `printer_kitchen` / `printer_cashier`: os nomes EXATOS das impressoras
     (a lista aparece quando o programa arranca).
4. **Desligar a ponte no tablet** (senão imprime a dobrar).

## Arrancar sempre com o Windows
1. Tecla Windows + R → escrever `shell:startup` → Enter.
2. Criar um atalho para `PrintBridge.exe` dentro dessa pasta.

Fica a correr numa janela; para testar, faz um pedido e vê "Impresso job ...".

## Notas
- Impressão RAW (bytes ESC/POS crus) — funciona com qualquer impressora
  instalada, independentemente do driver.
- Se uma impressão falhar, o programa continua e regista o erro na janela.
