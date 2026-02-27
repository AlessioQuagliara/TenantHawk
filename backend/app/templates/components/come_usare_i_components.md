# Data Table (Stile Filament)
Componente tabella completo in stile Filament con toolbar, filtri avanzati, ricerca, sorting, bulk actions e paginazione integrata.

## Uso Base:

### 1. Nel backend (route):
```python
@router.get("/users/table")
async def users_table(
    request: Request,
    page: int = Query(1, ge=1),
    search: str = Query(""),
    per_page: int = Query(10, ge=1, le=100),
    filter_role: str = Query(""),
    filter_status: str = Query(""),
):
    # Query database con filtri
    users_list = []  # Lista di dict o oggetti
    total = 0
    
    pagination = Pagination(page, per_page, total)
    
    current_filters = {}
    if filter_role:
        current_filters["filter_role"] = filter_role
    if filter_status:
        current_filters["filter_status"] = filter_status
    
    return templates.TemplateResponse(
        "admin/partials/table.html",
        {
            "request": request,
            "users": users_list,
            "pagination": pagination,
            "current_filters": current_filters,
            "search_value": search,
        }
    )
```

### 2. Nel template partial (es: admin/partials/users_table.html):
```jinja2
{% from "components/table.html" import data_table %}

{% set columns = [
  {
    'key': 'name',
    'label': 'Nome',
    'sortable': true
  },
  {
    'key': 'email',
    'label': 'Email',
    'sortable': true,
    'align': 'left'
  },
  {
    'key': 'role',
    'label': 'Ruolo',
    'render': lambda row: '<span class="badge">' + row.get('role') + '</span>'
  },
  {
    'key': 'created_at',
    'label': 'Data',
    'align': 'right'
  }
] %}

{% set config = {
  'selectable': true,
  'searchable': true,
  'search_placeholder': 'Cerca utenti...',
  'empty_message': 'Nessun utente trovato',
  'filters': [
    {
      'name': 'role',
      'label': 'Ruolo',
      'type': 'select',
      'placeholder': 'Tutti i ruoli',
      'options': [
        {'value': 'admin', 'label': 'Admin'},
        {'value': 'user', 'label': 'Utente'}
      ]
    },
    {
      'name': 'created_date',
      'label': 'Data creazione',
      'type': 'date'
    }
  ],
  'bulk_actions': [
    {
      'label': 'Elimina selezionati',
      'endpoint': '/admin/users/bulk-delete',
      'method': 'POST',
      'class': 'text-white bg-red-600 hover:bg-red-700',
      'confirm': "confirm('Confermi eliminazione?')"
    },
    {
      'label': 'Esporta CSV',
      'endpoint': '/admin/users/export',
      'method': 'POST',
      'class': 'text-white bg-blue-600 hover:bg-blue-700'
    }
  ],
  'per_page_options': [10, 25, 50, 100]
} %}

{{ data_table(
  id="users-table",
  endpoint="/admin/users/table",
  columns=columns,
  rows=users,
  pagination=pagination,
  config=config,
  current_filters=current_filters | default({}),
  search_value=search_value | default('')
) }}
```

## Parametri Config:
- **selectable**: bool - Abilita checkbox per selezione multipla
- **searchable**: bool - Mostra barra di ricerca
- **search_placeholder**: str - Placeholder per input search
- **filters**: list - Lista di filtri disponibili (select, date)
- **bulk_actions**: list - Azioni su selezione multipla
- **empty_message**: str - Messaggio quando non ci sono dati
- **empty_icon**: str - SVG custom per empty state
- **per_page_options**: list - Opzioni per items per pagina

## Rendering Celle Custom:
```python
# Con lambda inline
'render': lambda row: f'<a href="/users/{row["id"]}">{row["name"]}</a>'

# Con badge condizionali
'render': lambda row: '<span class="badge-' + ('success' if row['active'] else 'danger') + '">' + row['status'] + '</span>'

# Con icone
'render': lambda row: '<div class="flex items-center"><svg>...</svg>' + row['name'] + '</div>'
```

## Azioni Inline (invece di colonna actions):
Usa il rendering custom per aggiungere azioni inline:
```python
{
  'key': 'name',
  'label': 'Nome',
  'render': lambda row: f'''
    <div class="flex items-center justify-between">
      <span>{row["name"]}</span>
      <button hx-get="/admin/users/{row["id"]}/edit" 
              hx-target="#modal-container"
              class="text-primary-600 hover:text-primary-900">
        Modifica
      </button>
    </div>
  '''
}
```

## Bulk Actions Backend:
```python
@router.post("/users/bulk-delete")
async def users_bulk_delete(
    request: Request,
    ids: list[int] = Form(...)
):
    # Elimina users con IDs in ids
    # ...
    
    # Restituisci tabella aggiornata
    return RedirectResponse(
        url="/admin/users/table",
        status_code=status.HTTP_303_SEE_OTHER
    )
```

---

# Toast
Serve per mostrare messaggi rapidi (successo/errore/info) senza scrivere JS custom.

1) Metti il container **una sola volta** nel layout (es. `templates/admin/base.html`):
```html
<div id="toast-container" class="fixed top-4 right-4 z-50 flex flex-col gap-2"></div>
```

2) Aggiungi una volta nel CSS globale:
```css
[x-cloak] { display:none !important; }
```

3) Uso (consigliato) dentro una response HTMX (append globale con OOB):
```jinja2
{% from "components/toast.html" import toast_oob %}
{{ toast_oob("Salvato!", type="success") }}
```

Oppure inline:
```jinja2
{% from "components/toast.html" import toast %}
{{ toast("Errore nel salvataggio", type="error", duration=5000) }}
```

---

# Badges
Piccole etichette per stati (attivo/inattivo, ruolo, ecc.).

Uso:
```jinja2
{% from "components/badges.html" import success, warning, danger, info %}

{{ success("Attivo") }}
{{ warning("In attesa") }}
{{ danger("Bloccato") }}
{{ info("Editor") }}
```

Se ti serve aggiungere attributi (es. `id`, `title`, `class` extra):
```jinja2
{{ success("Attivo", attrs={"title":"Stato utente"}) }}
```

---

# Buttons
Bottoni riutilizzabili con stile coerente.

Uso:
```jinja2
{% from "components/button.html" import primary, secondary, danger, outline %}

{{ primary("Salva", type="submit") }}
{{ secondary("Annulla", attrs={"@click":"open=false"}) }}
{{ danger("Elimina") }}
{{ outline("Dettagli") }}
```

---

# Modal
Finestra modale generica. Si apre/chiude con eventi Alpine (senza JS extra).

1) Inserisci il modal nella pagina:
```jinja2
{% from "components/modal.html" import modal %}

{{ modal(
  id="delete-user",
  title="Eliminare utente?",
  content="Questa azione non è reversibile.",
  confirm_text="Elimina",
  cancel_text="Annulla",
  confirm_hx_post="/admin/users/123/delete",
  confirm_hx_target="#users-table",
  confirm_hx_swap="outerHTML"
) }}
```

2) Aprilo da qualunque bottone/link:
```html
<button class="btn" @click="window.dispatchEvent(new CustomEvent('open-modal', { detail: 'delete-user' }))">
  Apri modal
</button>
```

3) Per chiuderlo da codice (opzionale):
```html
<button @click="window.dispatchEvent(new CustomEvent('close-modal', { detail: 'delete-user' }))">Chiudi</button>
```

Note:
- ESC chiude il modal.
- Clic sul backdrop chiude il modal.

---

# Theme selector
Bottone per switchare light/dark. Usa Alpine e salva la scelta in `localStorage`.

Uso (in header o navbar):
```jinja2
{% include "components/theme_selector.html" %}
```