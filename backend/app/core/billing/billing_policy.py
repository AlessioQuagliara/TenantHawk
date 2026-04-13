# =============================================================================
# backend/app/core/billing_policy.py
# =============================================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Sottoscrizione,
    Sottoscrizioni,
    SottoscrizioniStati,
    Tenant,
    TokenResetPassword,
    Utente,
    UtenteRuoloTenant,
)

from app.core.billing.billing_models import (
    GIORNI_PROVA_DEFAULT,
    _calcola_scadenza_tregua,
    _e_scadenza_tregua,
    _normalizza_data_utc,
)

from app.core.billing.billing_sync import sincronizza_sottoscrizione_tenant_live


async def crea_sottoscrizione_trial_tenant(
    db: AsyncSession,
    *,
    tenant_id: int,
    giorni_prova: int = GIORNI_PROVA_DEFAULT,
) -> Sottoscrizione:
    # Nessuna integrazione Stripe: il trial e' gestito solo via DB.
    risultato = await db.execute(
        select(Sottoscrizione)
        .where(Sottoscrizione.tenant_id == tenant_id)
        .limit(1)
    )

    sottoscrizione_esistente = risultato.scalar_one_or_none()
    if sottoscrizione_esistente is not None:
        return sottoscrizione_esistente

    fine_trial = datetime.now(timezone.utc) + timedelta(days=max(giorni_prova, 1))
    nuova_sottoscrizione = Sottoscrizione(
        tenant_id=tenant_id,
        piano=Sottoscrizioni.BASE,
        stato_piano=SottoscrizioniStati.PROVA,
        fine_periodo_corrente=fine_trial,
        id_stripe_cliente=None,
        id_stripe_sottoscrizione=None,
    )

    db.add(nuova_sottoscrizione)
    await db.flush()
    return nuova_sottoscrizione


async def elimina_tenant_e_cascade(
    db: AsyncSession,
    *,
    tenant_id: int,
) -> None:
    risultato_utenti_primari = await db.execute(
        select(Utente).where(Utente.tenant_id == tenant_id)
    )
    utenti_primari = risultato_utenti_primari.scalars().all()
    utenti_primari_ids = [utente.id for utente in utenti_primari]

    utenti_condivisi_tenant_target: dict[int, int] = {}
    if utenti_primari_ids:
        risultato_ruoli_altri_tenant = await db.execute(
            select(UtenteRuoloTenant.utente_id, UtenteRuoloTenant.tenant_id)
            .where(
                UtenteRuoloTenant.utente_id.in_(utenti_primari_ids),
                UtenteRuoloTenant.tenant_id != tenant_id,
            )
            .order_by(
                UtenteRuoloTenant.utente_id.asc(),
                UtenteRuoloTenant.tenant_id.asc(),
            )
        )
        for utente_id, tenant_target_id in risultato_ruoli_altri_tenant.all():
            if utente_id not in utenti_condivisi_tenant_target:
                utenti_condivisi_tenant_target[utente_id] = int(tenant_target_id)

    utenti_da_eliminare_ids: list[int] = []
    for utente in utenti_primari:
        tenant_target_id = utenti_condivisi_tenant_target.get(utente.id)
        if tenant_target_id is None:
            utenti_da_eliminare_ids.append(utente.id)
            continue
        # Manteniamo l'account se e' gia' associato ad altri tenant.
        utente.tenant_id = tenant_target_id

    await db.execute(
        delete(UtenteRuoloTenant).where(UtenteRuoloTenant.tenant_id == tenant_id)
    )

    if utenti_da_eliminare_ids:
        await db.execute(
            delete(TokenResetPassword).where(
                TokenResetPassword.utente_id.in_(utenti_da_eliminare_ids)
            )
        )
        await db.execute(
            delete(UtenteRuoloTenant).where(
                UtenteRuoloTenant.utente_id.in_(utenti_da_eliminare_ids)
            )
        )
        await db.execute(delete(Utente).where(Utente.id.in_(utenti_da_eliminare_ids)))

    await db.execute(delete(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant_id))
    await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def applica_policy_disattivazione_tenant(
    db: AsyncSession,
    *,
    tenant_obj: Tenant,
) -> bool:
    """
    Policy:
    - stato ATTIVO/PROVA: nessuna cancellazione
    - stato SCADUTO/CANCELLATO: entra in SOSPESO per 14 giorni
    - stato SOSPESO: dopo 14 giorni, verifica live su Stripe e poi cancella in cascade
    """
    risultato_sottoscrizione = await db.execute(
        select(Sottoscrizione)
        .where(Sottoscrizione.tenant_id == tenant_obj.id)
        .limit(1)
    )
    sottoscrizione = risultato_sottoscrizione.scalar_one_or_none()
    if sottoscrizione is None:
        return False

    # Safety check: prima di azioni distruttive, allinea sempre stato live da Stripe.
    sottoscrizione, _, verifica_live_ok, _ = await sincronizza_sottoscrizione_tenant_live(
        db,
        tenant_obj=tenant_obj,
    )
    if sottoscrizione is None:
        return False
    ha_riferimenti_stripe = bool(
        sottoscrizione.id_stripe_sottoscrizione or sottoscrizione.id_stripe_cliente
    )
    if ha_riferimenti_stripe and not verifica_live_ok:
        # Fail-safe: se esistono riferimenti Stripe ma la verifica live non e' riuscita,
        # non applichiamo policy distruttive.
        return False

    stato = sottoscrizione.stato_piano
    if stato in {SottoscrizioniStati.ATTIVO, SottoscrizioniStati.PROVA}:
        return False

    adesso_utc = datetime.now(timezone.utc)
    fine_periodo_utc = _normalizza_data_utc(sottoscrizione.fine_periodo_corrente)

    if stato in {SottoscrizioniStati.SCADUTO, SottoscrizioniStati.CANCELLATO}:
        try:
            # Rilegge lo stato dopo la sync live per evitare transizioni stale
            # (es. webhook pagamento arrivato subito dopo la scadenza trial).
            await db.refresh(sottoscrizione)
        except Exception:
            await db.rollback()
            return False

        if sottoscrizione.stato_piano in {
            SottoscrizioniStati.ATTIVO,
            SottoscrizioniStati.PROVA,
        }:
            return False

        fine_periodo_utc = _normalizza_data_utc(sottoscrizione.fine_periodo_corrente)
        if fine_periodo_utc is None or fine_periodo_utc <= adesso_utc:
            sottoscrizione.stato_piano = SottoscrizioniStati.SOSPESO
            sottoscrizione.fine_periodo_corrente = _calcola_scadenza_tregua(adesso_utc)
            await db.commit()
        return False

    if stato == SottoscrizioniStati.SOSPESO:
        if fine_periodo_utc is None:
            sottoscrizione.fine_periodo_corrente = _calcola_scadenza_tregua(adesso_utc)
            await db.commit()
            return False

        if not _e_scadenza_tregua(fine_periodo_utc):
            # Hardening: se lo stato arriva da Stripe con una data non marcata
            # (es. fine periodo fatturazione), trasformiamo prima in vera tregua.
            if fine_periodo_utc <= adesso_utc:
                sottoscrizione.fine_periodo_corrente = _calcola_scadenza_tregua(adesso_utc)
                await db.commit()
            return False

        if fine_periodo_utc > adesso_utc:
            return False

        # Ultima verifica live su Stripe prima delete definitivo.
        sottoscrizione, _, verifica_live_ok, _ = await sincronizza_sottoscrizione_tenant_live(
            db,
            tenant_obj=tenant_obj,
        )
        ha_riferimenti_stripe = bool(
            sottoscrizione
            and (sottoscrizione.id_stripe_sottoscrizione or sottoscrizione.id_stripe_cliente)
        )
        if ha_riferimenti_stripe and not verifica_live_ok:
            return False
        if (
            sottoscrizione is not None
            and sottoscrizione.stato_piano in {SottoscrizioniStati.ATTIVO, SottoscrizioniStati.PROVA}
        ):
            return False

        await elimina_tenant_e_cascade(
            db,
            tenant_id=tenant_obj.id,
        )
        await db.commit()
        return True

    return False
