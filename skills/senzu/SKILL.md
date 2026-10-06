---
name: senzu
# Hermes shows 60 characters of it in the skills index: the trigger has to fit.
description: Bloqué (accès, panne, outil) ou on demande Senzu ou Édouard
version: 0.4.2
author: Senzu
license: MIT
metadata:
  hermes:
    tags: [support, maintenance, handover]
---

# Senzu

Senzu's technicians repair what stops this assistant from working: they connect services,
open accesses, fix the server, the tools and the integrations, whatever the subject, work or
personal. They do not do the work itself when you can do it.

## When

- You cannot do what is asked for lack of an access, a connection, a right or an integration,
  or because a tool, the server or a service is broken or blocks you.
- You have tried and it keeps failing.
- The person asks for help, support, a technician, their provider, Senzu, or Édouard (who runs
  Senzu): « j'aimerais qu'Édouard intervienne », « demande à Senzu », « appelle le support ».

When the person asks, do it every time. When you are the one noticing, say plainly what you
cannot do, then offer Senzu in one sentence; if they decline, do not bring it up again for
that subject.

## How much

Read the scale with `mcp__senzu__read_resource` (uri `senzu://tarifs`) and apply it to what you
observed to give an estimate: the nature of the problem gives points, the situation adds some,
the total is rounded up the Fibonacci sequence, and the points give a price before tax and a
lead time. The desk computes it again when you file; its figure is the one shown. On an
installation in alpha, nothing is billed: say so and give no amount.

## Steps

1. Tell the person, in three short lines, what you will send: what they want, what is in the
   way, what was already tried; and the estimate.
2. Ask whether they want to add anything (what they tried on their side, a detail), and wait
   for the answer.
3. Call `mcp__senzu__senzu_signaler` with:
   - `objectif`, `blocage`, `tentatives`, `systemes`, `urgence`, `climat` from the conversation;
   - `extrait`: their own words, one sentence;
   - the facts the scale prices: `nature` (`reglage` for a setting or a simple action such as
     a restart; `connexion` only for a service not connected yet; `automatisation`, `donnees`,
     `diagnostic`, `contournement`, `sur_mesure`), `serveur`, `cause_inconnue`,
     `irreversible`, `tiers`. Count only what the case really needs: small jobs are small
     tickets.
   Never a password, a key, a token or a customer identifier.
4. Give them the link it returns, for them only. The first time, it asks for their consent to
   share the summary; afterwards it lets them validate, or pay, the intervention. Nothing starts
   before they do.
5. Follow up with `mcp__senzu__senzu_statut` when they ask where it stands; their invoices come
   from `mcp__senzu__senzu_factures`. News from Senzu reaches their chat on its own.
