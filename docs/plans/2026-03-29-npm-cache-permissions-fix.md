# npm Cache Permissions Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restaurar as permissões do diretório `~/.npm` para permitir que o `npx` rode sem erros de `EACCES`.

**Architecture:** Executar `sudo chown -R $USER ~/.npm` para garantir que o usuário logado seja o dono de todos os arquivos no cache.

**Tech Stack:** Shell (bash/zsh), npm/npx.

---

### Task 1: Verificação Final e Aplicação do Fix

**Files:**
- N/A (Modificação de sistema/diretório de cache)

**Step 1: Verificar arquivos pertencentes ao root (Failing check)**

```bash
find ~/.npm -user root | head -n 5
```
Expected: Listar arquivos se o problema persistir.

**Step 2: Executar a correção de permissões**

```bash
sudo chown -R $(whoami) ~/.npm
```
Expected: Solicitar senha (se não estiver em cache) e rodar sem erros.

**Step 3: Verificar que não há mais arquivos do root**

```bash
find ~/.npm -user root
```
Expected: Nenhuma saída (sucesso).

**Step 4: Validar com npm cache verify**

```bash
npm cache verify
```
Expected: "Content-addressable store is valid" e logs de sucesso.

**Step 5: Commit do log de design (opcional)**

```bash
git add docs/plans/2026-03-29-npm-cache-permissions-design.md
git commit -m "docs: add design for npm cache permission fix"
```

### Task 2: Validação no Servidor MCP

**Files:**
- Modify: `mcp_config.json` (apenas para garantir que o servidor está habilitado para teste)

**Step 1: Habilitar o servidor insforge para teste**

No arquivo `mcp_config.json`, mude `"disabled": true` para `"disabled": false` no bloco do `insforge`.

**Step 2: Observar logs ou tentar inicializar**

Tente rodar o comando que falha:
```bash
npx -y @insforge/mcp@latest --help
```
Expected: Saída de ajuda do pacote, sem erros de permissão de cache.

**Step 3: Commit das alterações de config (se mantidas)**

```bash
git add mcp_config.json
git commit -m "chore: enable insforge mcp server for validation"
```
