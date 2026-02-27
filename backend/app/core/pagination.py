# =============================================================================
# backend/app/core/pagination.py
# =============================================================================

from __future__ import annotations


class Pagination:
    """
    Classe per gestire la paginazione lato server.
    I dati vengono forniti esternamente; la classe calcola i metadati necessari al template.
    """

    def __init__(self, page: int, per_page: int, total: int):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.total_pages = (total + per_page - 1) // per_page if total else 1
        self.has_prev = page > 1
        self.has_next = page < self.total_pages
        self.prev_num = page - 1 if self.has_prev else None
        self.next_num = page + 1 if self.has_next else None
        self.start = (page - 1) * per_page + 1 if total > 0 else 0
        self.end = min(page * per_page, total)

        # Genera l'elenco delle pagine (con eventuali ellissi) per il template
        self.pages = self._generate_page_numbers()

    def _generate_page_numbers(self):
        """Restituisce una lista di numeri di pagina e None per gli ellissi."""
        if self.total_pages <= 7:
            return list(range(1, self.total_pages + 1))

        pages = []
        for i in range(1, self.total_pages + 1):
            if i == 1 or i == self.total_pages or (self.page - 2 <= i <= self.page + 2):
                pages.append(i)
            elif i == self.page - 3 or i == self.page + 3:
                pages.append(None)  # ellissi
        return pages