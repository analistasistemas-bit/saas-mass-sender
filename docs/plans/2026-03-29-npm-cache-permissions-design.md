# Design de Correção: Permissões do Cache npm (~/.npm)

**Data:** 2026-03-29
**Autor:** Antigravity AI
**Problema:** Erro de permissão (`EACCES` e `EEXIST`) ao tentar rodar `npx` para inicializar servidores MCP (como `insforge`).

## 1. Contexto e Investigação do Root Cause
- Investigação mostrou que diversos arquivos dentro de `~/.npm/_cacache` são de propriedade do usuário `root`.
- Isso bloqueia o comando `npx` executado pelo usuário `diego` de modificar o cache e instalar novos pacotes.

## 2. Requisitos e Design da Solução
- **Requisito:** O usuário `diego` deve ter controle total recursivo sobre seu próprio diretório de cache (`~/.npm`).
- **Abordagem:** Execução de `sudo chown -R $USER ~/.npm` para retomar a posse dos arquivos e diretórios protegidos.

## 3. Plano de Teste (Validação)
- Verificação manual de quem é o proprietário dos arquivos no cache após a correção.
- Tentativa de reinicialização do servidor MCP `insforge` com sucesso sem os logs de erro observados.

## 4. Próximos Passos (Implementação)
Seguir para o plano de implementação detalhado para executar as correções de sistema necessárias.
