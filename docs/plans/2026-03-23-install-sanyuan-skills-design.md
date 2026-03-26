---
name: plan-install-sanyuan-skills
description: Planejamento para a instalação e configuração das skills do repositório sanyuan-skills
---

# Design: Instalação e Configuração das Sanyuan Skills

## 1. Contexto e Objetivos
O usuário deseja instalar e configurar o conjunto de skills fornecido em `https://github.com/sanyuan0704/sanyuan-skills`. Estas skills incluem ferramentas para revisão de código expert, sessões de tutoria (Sigma) e criação de novas skills (Skill Forge).

## 2. Abordagens Propostas

### Opção A: Instalação via Ferramenta de CLI (Recomendado no Repo)
Utilizar o comando `npx skills add` conforme sugerido no README do repositório.
- **Prós:** Segue o fluxo oficial do autor.
- **Contras:** Depende da ferramenta `skills` estar configurada corretamente para o ambiente Antigravity.

### Opção B: Instalação Manual (Cópia de Arquivos)
Clonar o repositório temporariamente e copiar os diretórios das skills para `~/.gemini/antigravity/skills/`.
- **Prós:** Garante que os arquivos estarão no local correto que o Antigravity utiliza para carregar skills. Independente de ferramentas externas.
- **Contras:** Requer passos manuais de cópia e verificação.

**Recomendação:** Opção B, pois garante a compatibilidade com o diretório de skills já identificado no sistema do usuário.

## 3. Arquitetura e Fluxo
1. Clonar o repositório `https://github.com/sanyuan0704/sanyuan-skills` em um diretório temporário.
2. Identificar as skills disponíveis em `skills/`.
3. Para cada skill (`code-review-expert`, `sigma`, `skill-forge`):
   - Criar o diretório correspondente em `/Users/diego/.gemini/antigravity/skills/`.
   - Copiar o arquivo `SKILL.md` e outros arquivos necessários.
4. Verificar se as skills são carregadas corretamente pelo sistema.

## 4. Próximos Passos
- Obter aprovação do usuário para a estratégia de instalação manual.
- Executar a clonagem e cópia.
- Validar o funcionamento.
