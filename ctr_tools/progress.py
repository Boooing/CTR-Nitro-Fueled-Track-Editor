"""Avancement de l'operation en cours, lu par l'editeur (barre de progression) pendant qu'elle tourne.

Une seule operation d'ecriture a la fois (l'editeur bloque ses boutons). Les etapes imbriquees (import -> modeles ->
collision) reportent leur avancement dans la tranche que leur donne l'appelant (span) ; sans begin(), tout est sans
effet (outils en ligne de commande, tests)."""
import contextlib
import threading
import time

_lock = threading.Lock()
_state = {'active': False}
_span = [0.0, 1.0]


def begin(label):
    global _span
    with _lock:
        _state.clear()
        _state.update(active=True, label=label, step='', frac=0.0, t0=time.time())
        _span = [0.0, 1.0]


def end():
    with _lock:
        _state['active'] = False


def step(text=None, frac=None):
    """Texte de l'etape et/ou avancement (0..1) dans la tranche courante (la barre ne recule jamais)."""
    if not _state.get('active'):
        return
    with _lock:
        if text is not None:
            _state['step'] = text
        if frac is not None:
            lo, hi = _span
            _state['frac'] = max(_state['frac'], lo + (hi - lo) * min(1.0, max(0.0, frac)))


@contextlib.contextmanager
def span(a, b, text=None):
    """Sous-operation occupant [a, b] de la tranche courante."""
    global _span
    old = list(_span)
    step(text, a)
    _span = [old[0] + (old[1] - old[0]) * a, old[0] + (old[1] - old[0]) * b]
    try:
        yield
    finally:
        _span = old
        step(None, b)


def items(seq, text, a=0.0, b=1.0):
    """Parcourt seq en avancant la barre de a a b (dans la tranche courante) ; text peut contenir {i} et {n}."""
    seq = list(seq)
    n = len(seq)
    for i, x in enumerate(seq):
        step(text.format(i=i + 1, n=n), a + (b - a) * i / max(1, n))
        yield x
    step(None, b)


def get():
    with _lock:
        d = dict(_state)
    if d.get('active'):
        d['elapsed'] = round(time.time() - d.pop('t0'), 1)
    return d
