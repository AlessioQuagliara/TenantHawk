// =============================================================================
// frontend/app/lib/api
// =============================================================================

// chiamiamo il backend
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchHealt() {
    const risultato = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!risultato.ok) throw new Error("Errore di comunicazione con il backend");
    return risultato.json();
}