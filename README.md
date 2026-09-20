# ShowUp

App de agendamento com proteção contra no-show para profissionais autônomos
(personal trainers, esteticistas, terapeutas, etc.) — o cliente reserva um
horário, o cartão fica pré-autorizado (hold), e o profissional confirma se
o cliente compareceu. Se não compareceu, uma taxa é cobrada automaticamente;
se ninguém confirmar a tempo, o hold expira sem cobrar ninguém.

## Estrutura

- `backend/` — API em FastAPI + MongoDB (Motor/PyMongo) + Stripe (Payment
  Intents com hold/captura manual, Connect para repasse ao profissional,
  Billing para os planos de assinatura).
- `frontend/` — App em Expo/React Native (Expo Router), mobile-only
  (Android + iOS, sem versão web).

## Rodando localmente

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001
```
Precisa de um `.env` com `MONGO_URL`, `STRIPE_API_KEY`,
`INTERNAL_SERVICE_TOKEN`, entre outras — veja `backend/.env.example`.

### Frontend
```bash
cd frontend
npm install
npx expo run:android   # ou run:ios
```
Precisa de um `.env` com `EXPO_PUBLIC_BACKEND_URL` e
`EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` — veja `frontend/.env.example`.

**Importante:** este app usa módulos nativos (Stripe Payment Sheet, push
notifications) que não funcionam no app Expo Go da loja — precisa de um
development build (`npx expo run:android`/`run:ios` local, ou
`eas build --profile development`).

## Testes

```bash
cd backend
TESTING=1 uvicorn server:app --host 0.0.0.0 --port 8001 &
EXPO_PUBLIC_BACKEND_URL=http://127.0.0.1:8001 pytest
```
`TESTING=1` desliga o rate limiting só para a suíte não ser bloqueada por
suas próprias chamadas repetidas — nunca deve ser usado em produção.
