# Lite frontend (Ionic React)

Ionic React + Vite + Supabase, ready for web, iOS, and Android via
Capacitor. `IonSplitPane` + `IonMenu` give you a permanent sidebar on
tablet/desktop that automatically becomes an off-canvas drawer on
phone-sized screens — no separate mobile layout to maintain.

## Run it (web)

```
cd frontend
npm install
npm run dev
```

`.env` is already filled in with your Supabase project's URL and
publishable key.

## Run it on iOS / Android

```
npm run build
npx cap add ios       # first time only
npx cap add android    # first time only
npm run cap:sync
npx cap open ios       # or: npx cap open android
```

## Structure

```
src/
  pages/       ChatPage, LoginPage — one IonPage per route
  components/  AppMenu — the sidebar (IonMenu)
  hooks/       useAuth, useProjects, useConversations, useMessages
               — pure Supabase logic, no Ionic/React-DOM specifics,
               reusable if you ever add a second frontend
  lib/         supabase client, generated DB types, AI backend stub
  theme/       variables.css — Ionic's --ion-* color tokens
```

## What's wired up vs. stubbed

**Wired up:** email magic-link auth, sidebar (projects + unfiled chats,
New chat / New project), loading/sending conversations and messages
through Supabase with RLS enforcing per-user access, auto-titling a
chat from its first message.

**Stubbed:** `src/lib/aiBackend.ts` — the Python router
(`../backend/router.py`) is CLI-only right now, so there's no HTTP
endpoint yet for this to call. Sending a message currently gets a
placeholder reply. See that file for the exact request/response
contract it expects once you wrap the router in an API.

## Not built yet

- Realtime subscriptions (currently refetches after each mutation)
- Rename/delete UI for chats and projects (hooks already support it)
- Tier badge / Pro upsell in the menu, now that `backend/access/tiers.py` exists
