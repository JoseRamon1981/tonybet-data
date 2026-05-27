# Tonybet Advisor SaaS — Guía de configuración completa

## Resumen del proceso

```
1. Supabase  → base de datos de usuarios + autenticación   (~10 min)
2. Stripe    → cobro de suscripciones                       (~15 min)
3. Railway   → hosting de la app web                        (~5 min)
4. Conectar  → variables de entorno en Railway              (~5 min)
```

---

## PASO 1 — Supabase (base de datos + auth)

### 1.1 Crear cuenta
1. Ve a **https://supabase.com** → "Start your project" → regístrate con GitHub o email
2. Crea un nuevo proyecto:
   - **Name**: `tonybet-advisor`
   - **Database Password**: genera una contraseña segura y guárdala
   - **Region**: West EU (Ireland) — más cerca de España

### 1.2 Ejecutar el schema
1. En el dashboard de Supabase → menú izquierdo → **SQL Editor**
2. Pulsa "New query"
3. Copia y pega el contenido completo de `supabase_schema.sql`
4. Pulsa **Run** (botón verde)
5. Verifica que aparece "Success" y las tablas `users` y `bets` en Table Editor

### 1.3 Copiar las claves
1. Ve a **Project Settings** → **API**
2. Copia estos 3 valores (los necesitarás en el Paso 4):

```
SUPABASE_URL         = https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY    = eyJhbGci...    (public/anon key)
SUPABASE_SERVICE_KEY = eyJhbGci...    (service_role key — ¡no lo publiques!)
```

---

## PASO 2 — Stripe (pagos)

### 2.1 Crear cuenta
1. Ve a **https://stripe.com** → "Crear cuenta"
2. Rellena datos (nombre, email, país: España)
3. Puedes empezar en **modo Test** (sin verificación bancaria)

### 2.2 Crear los productos
En el dashboard de Stripe → **Catálogo** → **Productos** → "Añadir producto"

**Producto 1 — Plan Pro:**
- Nombre: `Tonybet Advisor Pro`
- Precio: `19,00 €` / mes (recurrente)
- Pulsa "Guardar" → copia el **Price ID** (empieza por `price_`)

**Producto 2 — Plan Premium:**
- Nombre: `Tonybet Advisor Premium`
- Precio: `49,00 €` / mes (recurrente)
- Pulsa "Guardar" → copia el **Price ID**

### 2.3 Copiar las claves
1. Ve a **Desarrolladores** → **Claves de API**
2. Copia:

```
STRIPE_SECRET_KEY   = sk_test_...   (en producción: sk_live_...)
STRIPE_PRICE_PRO    = price_...
STRIPE_PRICE_PREMIUM = price_...
```

> **Nota**: empieza con `sk_test_` (modo test) para probar sin dinero real.
> Cuando estés listo, activa tu cuenta y cambia a `sk_live_`.

---

## PASO 3 — Railway (hosting)

### 3.1 Crear cuenta
1. Ve a **https://railway.app** → "Login with GitHub"
2. Autoriza el acceso a tus repositorios

### 3.2 Crear el proyecto
1. Dashboard → **New Project** → **Deploy from GitHub repo**
2. Selecciona el repo `JoseRamon1981/tonybet-data`
3. Railway detectará automáticamente `railway.toml` y configurará el deploy

### 3.3 Obtener la URL pública
1. Ve a tu servicio → pestaña **Settings** → **Networking**
2. Pulsa **Generate Domain** → copia la URL (ej: `https://tonybet-advisor.railway.app`)

---

## PASO 4 — Variables de entorno en Railway

En el dashboard de Railway → tu servicio → pestaña **Variables** → añade:

```
SUPABASE_URL          = https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY     = eyJhbGci...
SUPABASE_SERVICE_KEY  = eyJhbGci...

STRIPE_SECRET_KEY     = sk_test_...
STRIPE_PRICE_PRO      = price_...
STRIPE_PRICE_PREMIUM  = price_...

APP_URL               = https://tu-app.railway.app   ← la URL del Paso 3.3

ANTHROPIC_API_KEY     = sk-ant-...
ODDS_API_KEY          = ...

BANKROLL              = 200
MAX_DAILY_STAKE       = 50
MAX_SINGLE_BET        = 10
KELLY_FRACTION        = 0.25
MIN_EV_THRESHOLD      = 0.01
```

Después de guardar las variables → Railway hace redeploy automático.

---

## PASO 5 — Verificar que todo funciona

Ejecuta el script de validación:

```bash
python validate_setup.py
```

O visita la URL de Railway y:
1. Regístrate con un email de prueba
2. Accede → deberías ver el plan "Gratuito"
3. Haz clic en "Upgrade a Pro" → te llevará a Stripe Checkout
4. Usa la tarjeta de prueba: `4242 4242 4242 4242` (cualquier fecha/CVV)
5. Vuelve a la app → deberías ver "Plan Pro" activo

---

## Poner en producción (cuando tengas usuarios reales)

1. En Stripe: activa tu cuenta (añade datos bancarios para recibir pagos)
2. Cambia `STRIPE_SECRET_KEY` de `sk_test_` a `sk_live_` en Railway
3. Crea nuevos productos en Stripe (modo Live) y actualiza los `STRIPE_PRICE_*`
4. ¡Listo para cobrar!

---

## Preguntas frecuentes

**¿Cuánto cuesta el hosting?**
- Railway: desde $5/mes (o gratis con límites)
- Supabase: gratis hasta 50.000 usuarios activos
- Stripe: 1.4% + 0.25€ por transacción europea

**¿Puedo probar sin pagar nada?**
Sí. Supabase y Railway tienen tier gratuito. Stripe tiene modo test completo.

**¿Cómo actualizo el advisor automáticamente?**
GitHub Actions ya está configurado (corre a las 9:00 y 17:00 hora española).
Asegúrate de tener en GitHub Secrets: `ANTHROPIC_API_KEY`, `ODDS_API_KEY`.
