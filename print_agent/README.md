# ============================================
# PIZZARIA PRINT AGENT - GUIA DE INSTALAÇÃO
# ============================================

## Requisitos
- Windows 10/11
- Python 3.8 ou superior
- Impressora térmica ESC/POS com conexão de rede (TCP/IP)
- Acesso à rede onde a impressora está conectada

## Passo 1: Instalar Python

1. Aceda a https://www.python.org/downloads/
2. Descarregue o instalador para Windows
3. Durante a instalação, MARQUE a opção "Add Python to PATH"
4. Complete a instalação

## Passo 2: Configurar as Impressoras no Sistema

1. Aceda ao Admin do sistema: https://seu-dominio.com/admin
2. Faça login com as suas credenciais
3. Vá em "Impressoras" no menu lateral
4. Adicione as impressoras:
   - Nome: Ex: "Cozinha", "Balcão"
   - IP: Endereço IP fixo da impressora na rede local
   - Porta: 9100 (padrão para impressoras ESC/POS)
   - Largura: 80mm ou 58mm (conforme o modelo)
   - Cortar papel: Sim (se suportado)
   - Ativa: Sim

## Passo 3: Obter a API Key

1. No Admin, vá em "Definições" > "Print Agent"
2. Copie a API Key apresentada
3. Guarde num local seguro

## Passo 4: Configurar o Print Agent

1. Abra o ficheiro `print_agent.py` num editor de texto
2. Altere as configurações:
   
   ```python
   BACKEND_URL = "https://seu-dominio.com"
   API_KEY = "cole_sua_api_key_aqui"
   ```

3. Guarde o ficheiro

## Passo 5: Iniciar o Print Agent

### Opção A: Execução Manual
1. Dê duplo clique em `iniciar_agent.bat`
2. O agent irá iniciar e mostrar mensagens no console

### Opção B: Iniciar com o Windows (Recomendado)
1. Pressione Win + R
2. Digite: shell:startup
3. Crie um atalho para `iniciar_agent.bat` nesta pasta
4. O agent iniciará automaticamente com o Windows

### Opção C: Como Serviço Windows (Avançado)
1. Descarregue o NSSM: https://nssm.cc/download
2. Extraia e execute como Administrador:
   ```
   nssm install PizzariaPrintAgent
   ```
3. Configure:
   - Path: C:\Python39\python.exe
   - Startup directory: C:\caminho\para\print_agent
   - Arguments: print_agent.py
4. Inicie o serviço

## Configuração da Impressora na Rede

### Configurar IP Fixo na Impressora

A maioria das impressoras térmicas tem um painel de configuração ou podem ser
configuradas via comandos. Consulte o manual da sua impressora para:

1. Definir um IP fixo (ex: 192.168.1.100)
2. Confirmar que a porta 9100 está ativa
3. Desativar DHCP se necessário

### Testar Conexão

No Windows, abra o Prompt de Comando e execute:
```
telnet 192.168.1.100 9100
```

Se conectar (tela preta), a impressora está acessível.
Se der erro, verifique:
- Cabo de rede
- IP da impressora
- Firewall do Windows

### Impressoras Compatíveis

O sistema é compatível com impressoras que suportam ESC/POS via TCP:
- Epson TM-T20, TM-T88
- Star TSP100, TSP650
- Bixolon SRP-350
- Elgin i9
- Daruma DR800
- E outras compatíveis ESC/POS

## Resolução de Problemas

### "API Key inválida"
- Verifique se copiou a API Key correctamente
- Regenere a API Key no Admin se necessário

### "Timeout ao conectar"
- Verifique se o IP da impressora está correcto
- Confirme que a impressora está ligada e na mesma rede
- Teste com: telnet IP_IMPRESSORA 9100

### "Conexão recusada"
- A impressora pode estar offline
- A porta 9100 pode estar bloqueada
- Verifique as configurações de rede da impressora

### Impressora não imprime
- Verifique se há papel
- Confirme a largura configurada (58mm vs 80mm)
- Teste com o botão "Imprimir Teste" no Admin

## Logs

Os logs são guardados em:
```
print_agent/logs/print_agent_YYYYMMDD.log
```

Consulte os logs para diagnosticar problemas.

## Suporte

Para questões técnicas, consulte a documentação ou contacte o suporte.
