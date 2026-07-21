# Ponte de Impressão · Lenha e Brasa (APK Android)

App Android **mínima** que serve de **ponte** entre o sistema de pedidos
(`pedido.lenhaebrasa.com`) e as impressoras térmicas de rede. Não tem interface
de operação — só configuração. Corre em **segundo plano** (foreground service)
no tablet e imprime os talões automaticamente.

## Como funciona

1. Um **serviço em primeiro plano** (com notificação permanente) faz *polling* a
   cada N segundos ao endpoint `GET /api/agent/pending-jobs` (header `X-API-Key`).
2. Para cada talão pendente, recebe os **bytes ESC/POS já prontos** (campo
   `escpos_base64`, gerado pelo backend), abre um **socket TCP na porta 9100** para
   o IP da impressora correspondente e imprime.
3. Confirma o resultado em `PUT /api/agent/jobs/{id}/status` (`printed` ou `failed`).

O roteamento é por **tipo**: talões de **cozinha** (`kitchen`) vão para o IP da
impressora da cozinha; a **consulta de mesa** (`cashier`) vai para o IP da caixa.

> Nota: a **fatura fiscal (FR)** continua a ser emitida pelo Vendus no fecho — a
> ponte imprime pedidos de cozinha e a consulta de mesa (conta provisória), não a fatura.

## Hardware previsto

- **Tablet:** Samsung Galaxy Tab A7 (Android 10+), ligado à corrente, mesma rede
  das impressoras.
- **Impressoras (rede, ESC/POS, porta 9100):**
  - iggual TP8002 → **cozinha**
  - Epson TM-m30 → **caixa**

Dá a cada impressora um **IP fixo** na rede (no router, por reserva DHCP) para os
IPs não mudarem.

## Instalar no tablet

1. Copia o `app-debug.apk` para o tablet (cabo/USB, Google Drive, etc.).
2. No tablet: **Definições → Segurança → Instalar apps desconhecidas** → permite o
   instalador que vais usar.
3. Abre o APK e instala.

## Configurar

Abre a app **Impressão · Lenha e Brasa** e preenche:

- **URL do servidor:** `https://pedido.lenhaebrasa.com`
- **API Key:** a `PRINT_AGENT_API_KEY` do servidor (a mesma do `backend/.env`).
- **IP impressora COZINHA:** ex. `192.168.1.50`
- **IP impressora CAIXA:** ex. `192.168.1.51`
- **Intervalo:** 3 (segundos)

Carrega em **Testar cozinha** / **Testar caixa** para confirmar que cada impressora
responde. Depois **Iniciar**.

## Manter vivo em segundo plano (IMPORTANTE no Samsung)

O One UI mata apps em segundo plano de forma agressiva. Faz **uma vez**:

1. Na app, carrega em **"Desativar poupança de bateria"** e aceita.
2. **Definições → Bateria → Limites de utilização em segundo plano →** garante que
   a app **não** está em "Apps em suspensão / suspensão profunda"; se possível,
   adiciona-a às **"Apps nunca em suspensão"**.
3. **Definições → Ecrã → Suspensão do ecrã:** o mais longo possível (ou usa modo
   quiosque). Mantém o tablet **sempre ligado à corrente**.

A app volta a arrancar sozinha depois de um reinício do tablet.

## Compilar a partir do código

Requisitos: Android SDK + um JDK 17+ (serve o do Android Studio).

```bash
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
./gradlew assembleDebug        # gera app/build/outputs/apk/debug/app-debug.apk
```

Para uma versão assinada de distribuição (`assembleRelease`) é preciso criar uma
keystore própria — para uso interno num tablet, o `app-debug.apk` chega.

## Dependência do backend

Precisa que o backend inclua o campo `escpos_base64` em `/api/agent/pending-jobs`
(já implementado em `backend/server.py`, função `get_pending_jobs_for_agent`).
