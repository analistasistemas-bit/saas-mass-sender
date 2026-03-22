# Design: Reprocessar Falhados Apos Campanha Concluida

## Objetivo

Adicionar uma acao explicita para reenfileirar apenas contatos com falha depois que a campanha ja estiver `completed`, sem substituir a acao atual de reiniciar toda a campanha.

## Abordagem

O backend ja suporta `restart_campaign(..., "failed")`. A mudanca sera concentrada em dois pontos:

- expor na UI um botao secundario `Reprocessar falhados` ao lado de `Exportar falhas` quando `status == completed` e `failed > 0`
- adicionar um bloco proprio na secao de resultados para sinalizar que houve reprocessamento parcial, com contagem da fila reenfileirada e estado atual desse reprocessamento

## Regras

- `Reiniciar campanha` continua existindo e segue recriando a fila completa
- `Reprocessar falhados` deve chamar o endpoint existente com `mode=failed`
- o card principal de resultados de campanha concluida nao sera alterado; o reprocessamento aparecera em uma area separada dentro da mesma secao
- os indicadores devem desaparecer quando nao houver historico de reprocessamento parcial

## Impacto tecnico

- `services/campaign_service.py`: incluir no payload de resultados um bloco opcional `reprocessing`
- `static/app.js`: renderizar nova acao secundaria e o bloco visual de reprocessamento
- `templates/campaign.html`: reservar container para o novo bloco
- testes: backend para payload, e2e para visibilidade da nova acao
