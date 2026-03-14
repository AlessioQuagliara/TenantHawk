// =============================================================================
// test/test_login.js
// =============================================================================

import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE_URL = 'http://admin.localhost:8000'

export const options = {
  vus: 700,        // utenti virtuali concorrenti
  duration: '30s', // durata del test
}

export default function () {

  // ---- Step 1: GET /auth/login per ottenere CSRF token -------------------
  const loginPageRes = http.get(`${BASE_URL}/auth/login`)
  
  check(loginPageRes, {
    'login page status è 200': r => r.status === 200,
  })

  // Estrai CSRF token e sessione_temp dall'HTML usando regex
  const csrfMatch = loginPageRes.body.match(/name="csrf_token" value="([^"]+)"/)
  const sessionTempMatch = loginPageRes.body.match(/name="sessione_temp" value="([^"]+)"/)

  if (!csrfMatch || !sessionTempMatch) {
    console.error('CSRF token o sessione_temp non trovati nella pagina login')
    return
  }

  const csrfToken = csrfMatch[1]
  const sessioneTemp = sessionTempMatch[1]

  // ---- Step 2: POST /auth/login con CSRF token ----------------------------
  const loginRes = http.post(
    `${BASE_URL}/auth/login`,
    {
      email: 'info@spotexsrl.it',         // Sostituisci con tue credenziali
      password: 'latuapassword@',
      csrf_token: csrfToken,              // ← AGGIUNTO
      sessione_temp: sessioneTemp,        // ← AGGIUNTO
      next: '/',
    },
    {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      redirects: 0, // Blocca redirect per ispezionare 303
    }
  )

  // ---- Step 3: Verifica risposta login ------------------------------------
  check(loginRes, {
    'login status è 303':                            r => r.status === 303,
    'header Location presente':                       r => r.headers['Location'] !== undefined,
    'cookie id_sessione_utente impostato':           r => r.cookies['id_sessione_utente'] !== undefined,
  })

  // ---- Step 4: Segui redirect con cookie sessione -------------------------
  const cookieValue = loginRes.cookies['id_sessione_utente']
    ? loginRes.cookies['id_sessione_utente'][0].value
    : null

  if (!cookieValue) {
    console.error('Cookie sessione non impostato dopo login')
    return
  }

  const redirectUrl = loginRes.headers['Location']

  const dashboardRes = http.get(
    `${BASE_URL}${redirectUrl}`,
    {
      headers: {
        Cookie: `id_sessione_utente=${cookieValue}`,
      },
    }
  )

  // ---- Step 5: Verifica dashboard caricata --------------------------------
  check(dashboardRes, {
    'dashboard status è 200':              r => r.status === 200,
    'dashboard contiene HTML':             r => r.headers['Content-Type'].includes('text/html'),
    'dashboard non ha errore sessione':    r => !r.body.includes('Sessione scaduta'),
  })

  sleep(1)
}
