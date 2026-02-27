# Come creare i moduli del gestionale

Se sai già che l’admin crescerà (dashboard, utenti, tenant, billing, cms, agency…), fare cartelle per modulo ti salva la vita dopo 2 settimane.

Il punto è scegliere una convenzione che resti leggibile e che si sposi bene con HTMX (partials).

Con la struttura attuale io farei così:

1.	Tieni padre/base.html come layout
2.	Dentro padre/ crea una cartella per ogni “modulo” o “area funzionale”
3.	Dentro ogni modulo separa:
    •	index.html (pagina intera)
    •	_list.html, _row.html, _form.html, _filters.html, _modal_*.html (partial HTMX)

Esempio struttura consigliata:
```
templates/
  admin/
    base.html
    dashboard/
      index.html
      _stats.html
      _activity.html

    users/
      index.html
      _table.html
      _row.html
      _form.html
      _filters.html
      _modal_delete.html

    tenants/
      index.html
      _table.html
      _row.html
      _form.html

    cms/
      pages/
        index.html
        _table.html
        _row.html
        _editor.html
      assets/
        index.html
        _grid.html
        _upload.html

    agency/
      clients/
        index.html
        _table.html
        _row.html
      projects/
        index.html
        _table.html
```

**Perché questo stile funziona bene?**
1. “Dove sta la pagina X?” lo trovi subito: <cartella_padre>/<modulo>/index.html
2. Con HTMX è naturale: ogni pezzo aggiornabile è un _partial.html
3. Non ti ritrovi una cartella "admin" con 200 file piatti
4. Quando aggiungi un modulo, aggiungi solo una directory