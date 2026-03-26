# Install Sanyuan Skills Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Instalar e configurar as skills `code-review-expert`, `sigma` e `skill-forge` do repositório `sanyuan0704/sanyuan-skills`.

**Architecture:** Clonar o repositório em `/tmp`, copiar as pastas das skills para o diretório de skills do Antigravity (`/Users/diego/.gemini/antigravity/skills/`) e verificar se há configurações adicionais necessárias nos arquivos `SKILL.md`.

**Tech Stack:** Git, Shell.

---

### Task 1: Clonar o Repositório

**Files:**
- Create: `/tmp/sanyuan-skills`

**Step 1: Clonar o repositório**

Run: `git clone https://github.com/sanyuan0704/sanyuan-skills /tmp/sanyuan-skills`
Expected: Repositório clonado com sucesso.

**Step 2: Listar as skills**

Run: `ls /tmp/sanyuan-skills/skills`
Expected: `code-review-expert`, `sigma`, `skill-forge` presentes.

### Task 2: Instalar a Skill Code Review Expert

**Files:**
- Create: `/Users/diego/.gemini/antigravity/skills/code-review-expert/`

**Step 1: Criar o diretório da skill**

Run: `mkdir -p /Users/diego/.gemini/antigravity/skills/code-review-expert`
Expected: Diretório criado.

**Step 2: Copiar os arquivos da skill**

Run: `cp -r /tmp/sanyuan-skills/skills/code-review-expert/* /Users/diego/.gemini/antigravity/skills/code-review-expert/`
Expected: Arquivos copiados.

### Task 3: Instalar a Skill Sigma

**Files:**
- Create: `/Users/diego/.gemini/antigravity/skills/sigma/`

**Step 1: Criar o diretório da skill**

Run: `mkdir -p /Users/diego/.gemini/antigravity/skills/sigma`
Expected: Diretório criado.

**Step 2: Copiar os arquivos da skill**

Run: `cp -r /tmp/sanyuan-skills/skills/sigma/* /Users/diego/.gemini/antigravity/skills/sigma/`
Expected: Arquivos copiados.

### Task 4: Instalar a Skill Skill Forge

**Files:**
- Create: `/Users/diego/.gemini/antigravity/skills/skill-forge/`

**Step 1: Criar o diretório da skill**

Run: `mkdir -p /Users/diego/.gemini/antigravity/skills/skill-forge`
Expected: Diretório criado.

**Step 2: Copiar os arquivos da skill**

Run: `cp -r /tmp/sanyuan-skills/skills/skill-forge/* /Users/diego/.gemini/antigravity/skills/skill-forge/`
Expected: Arquivos copiados.

### Task 5: Verificar Configuração e Limpeza

**Files:**
- Verify: `/Users/diego/.gemini/antigravity/skills/*/SKILL.md`

**Step 1: Verificar se as skills possuem requisitos de configuração**

Run: `grep -r "CONFIG" /Users/diego/.gemini/antigravity/skills/{code-review-expert,sigma,skill-forge}/SKILL.md`
Expected: Verificação concluída. Se houver configurações necessárias, informá-las ao usuário.

**Step 2: Limpar diretório temporário**

Run: `rm -rf /tmp/sanyuan-skills`
Expected: Diretório removido.
