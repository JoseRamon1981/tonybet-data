-- ============================================================
-- Tonybet Advisor SaaS — Supabase Schema
-- Run this in the Supabase Dashboard → SQL Editor
-- ============================================================

-- Users table (extends auth.users created by Supabase Auth)
CREATE TABLE IF NOT EXISTS public.users (
    id                  UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email               TEXT        NOT NULL,
    subscription_tier   TEXT        NOT NULL DEFAULT 'free'
                                    CHECK (subscription_tier IN ('free', 'pro', 'premium')),
    stripe_customer_id  TEXT,
    bankroll            FLOAT       NOT NULL DEFAULT 200.0,
    kelly_fraction      FLOAT       NOT NULL DEFAULT 0.25,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Bets table (per-user bet tracking)
CREATE TABLE IF NOT EXISTS public.bets (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    date            DATE        NOT NULL DEFAULT CURRENT_DATE,
    event           TEXT        NOT NULL,
    sport           TEXT,
    market          TEXT,
    selection       TEXT        NOT NULL,
    odds            FLOAT       NOT NULL,
    stake           FLOAT       NOT NULL DEFAULT 0,
    estimated_ev    FLOAT                DEFAULT 0,
    result          TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (result IN ('pending', 'won', 'lost', 'void')),
    profit          FLOAT       NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, event, selection, date)
);

-- ── Row Level Security ────────────────────────────────────────

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bets  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users: own row only"
    ON public.users FOR ALL
    USING (auth.uid() = id);

CREATE POLICY "bets: own rows only"
    ON public.bets FOR ALL
    USING (auth.uid() = user_id);

-- ── Auto-create user profile on signup ───────────────────────

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (id, email)
    VALUES (NEW.id, NEW.email)
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ── Auto-update updated_at ────────────────────────────────────

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
