"""Metodo da consulente per vendere, fare marketing e pianificare i progetti.

Richiesta di Alessandro del 2026-10-28: per i progetti da vendere e il
marketing JARVIS deve ragionare come i migliori marketer, venditori e project
manager. I metodi marketing sono condensati dalle skill installate in Claude
Code (campaign-plan, competitive-brief, content-creation, email-sequence);
vendita e pianificazione non hanno una skill installata e seguono pratiche
standard (offerta a pacchetti, prezzo sul valore, piano a milestone). Il
profilo dice di spingere a chiudere e monetizzare, non ad aprire nuovi fronti.

Si aggiunge al prompt solo quando la domanda tocca questi temi: le altre
risposte restano corte come prima.
"""
import re

_TOPICS = {
    "vendita": r"vend\w*|prezz\w*|preventiv\w*|offert\w*|pacchett\w*|canone|fee|tariff\w*|"
               r"quanto (posso )?chied\w*|clien\w*|trattativ\w*|contratt\w*|fattur\w*|monetizz\w*|commission\w*",
    "marketing": r"marketing|instagram|social|tiktok|linkedin|campagn\w*|lanci\w*|brand\w*|"
                 r"posizionament\w*|lead|funnel|contenut\w*|newsletter|\bseo\b|pubblicit\w*|\bads\b|concorrent\w*",
    "pianificazione": r"pianific\w*|roadmap|milestone|scadenz\w*|entro (fine|il|la)\w*|chiuder\w* il progetto|"
                      r"consegn\w*|prossimi (passi|step)|priorit\w*|piano\b",
}
_PATTERNS = {name: re.compile(r"\b(" + rule + r")", re.IGNORECASE) for name, rule in _TOPICS.items()}

_METHODS = {
    "vendita": (
        "Vendita (come un consulente commerciale senior): parti dal risultato che il cliente compra, non "
        "dalle ore. Offerta in tre pacchetti (base, consigliato, completo) con il consigliato in mezzo come "
        "ancora; voci una tantum separate dal canone mensile; scope scritto (cosa e' incluso, quante "
        "revisioni, tempi di risposta, cosa costa extra); durata minima e preavviso; acconto prima di "
        "iniziare. Prezzi in fasce motivate dal valore e dal mercato, dette come indicazione, mai inventate "
        "come dati. Anticipa le due obiezioni piu' probabili con la risposta. Chiudi sempre con il prossimo "
        "passo commerciale concreto: cosa mandare al cliente e entro quando."),
    "marketing": (
        "Marketing (come un responsabile marketing): obiettivo misurabile, pubblico preciso (chi compra, "
        "cosa gli importa, dove sta), un messaggio chiave con 2-3 prove, canali scelti tra propri, "
        "guadagnati e a pagamento in base a dove sta il pubblico e al budget, cadenza sostenibile (es. "
        "3 post a settimana su 3-4 temi fissi), una metrica per canale e quando controllarla. Per i "
        "concorrenti: cosa promettono, prezzo, punto debole da usare nel posizionamento. Mai pubblicare "
        "nulla senza l'ok di Alessandro o del cliente."),
    "pianificazione": (
        "Pianificazione (come un project manager): risultato finale e data, cosa e' dentro e cosa resta "
        "fuori, 3-5 milestone con data e criterio di 'fatto', dipendenze e cosa blocca (accessi, contenuti "
        "del cliente, pagamenti), i due rischi principali con la contromossa, e le tre azioni di questa "
        "settimana in ordine. Privilegia cio' che porta a consegnare e incassare prima; sconsiglia nuovi "
        "fronti finche' quelli aperti non sono chiusi."),
}


def topics(prompt: str) -> list[str]:
    return [name for name, pattern in _PATTERNS.items() if pattern.search(prompt or "")]


def matches(prompt: str) -> bool:
    return bool(topics(prompt))


def guidance(prompt: str, voice: bool = False) -> str:
    """Testo da aggiungere al prompt di sistema; vuoto se la domanda non tocca questi temi."""
    found = topics(prompt)
    if not found:
        return ""
    form = ("A voce: prima la raccomandazione in una frase, poi al massimo tre punti parlati, e "
            "chiudi con una sola domanda se manca un dato decisivo." if voice else
            "Struttura: raccomandazione in una frase, poi i punti essenziali, poi i prossimi passi "
            "con data; una sola domanda finale se manca un dato decisivo.")
    return ("\n\nQuesta domanda riguarda " + ", ".join(found) + " di un progetto. Rispondi da esperto, "
            "usando i dati del progetto che hai (memoria, note, file) e dicendo cosa e' stima.\n"
            + "\n".join(_METHODS[name] for name in found) + "\n" + form)
