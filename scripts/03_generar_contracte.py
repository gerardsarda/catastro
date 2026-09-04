# -*- coding: utf-8 -*-
"""
03_generar_contracte.py
-----------------------
Agafa un JSON de finca i escup un PDF del contracte amb les dades posades.
Una copia per finca.

Us:  python scripts/03_generar_contracte.py datos/finca_43060A00600107.json
"""
import json
import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# --- Estils tipografics -----------------------------------------------------
# ParagraphStyle = una "plantilla de format": tipus de lletra, mida, interliniat,
# alineacio i espais. Despres cada text es dibuixa amb un d'aquests estils.
TIT = ParagraphStyle("tit", fontName="Helvetica-Bold", fontSize=13, leading=16,
                     alignment=TA_CENTER, spaceAfter=2)
SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=12,
                     alignment=TA_CENTER, textColor="#444444", spaceAfter=10)
H = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10, leading=13,
                   spaceBefore=9, spaceAfter=4)
HC = ParagraphStyle("hc", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                    alignment=TA_CENTER, spaceBefore=10, spaceAfter=5)
P = ParagraphStyle("p", fontName="Helvetica", fontSize=9.2, leading=12.4,
                   alignment=TA_JUSTIFY, spaceAfter=5)
LI = ParagraphStyle("li", parent=P, leftIndent=10, bulletIndent=2, spaceAfter=3)
NOTA = ParagraphStyle("nota", fontName="Helvetica-Oblique", fontSize=7.6, leading=10,
                      alignment=TA_JUSTIFY, textColor="#555555", spaceBefore=12)
SIG = ParagraphStyle("sig", fontName="Helvetica", fontSize=9.2, leading=14, spaceBefore=4)


def milers(n):
    """8351 -> '8.351' (format europeu: punt com a separador de milers)."""
    return "{:,}".format(int(n)).replace(",", ".")


BUIT = "________________"

RUTA_VOCABULARI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "datos", "vocabulari_catastro.json")


def carregar_vocabulari():
    """Traduccions castella -> catala dels termes del Cadastre.

    El Cadastre contesta sempre en castella ('ALMENDRO REGADIO', 'Agrario') i
    el contracte va en catala. Les traduccions les revisa una persona UNA
    vegada al fitxer datos/vocabulari_catastro.json (el genera el script 06) i
    valen per a totes les fitxes. Si un terme no hi es tradut, es fa servir el
    literal del Cadastre: mes val que surti en castella que inventar-se'l.
    """
    if not os.path.exists(RUTA_VOCABULARI):
        return {"usos": {}, "conreus": {}}
    with open(RUTA_VOCABULARI, "r", encoding="utf-8") as fh:
        return json.load(fh)


def normalitza_finca(d):
    """Adapta la fitxa a la forma que espera aquest generador.

    Hi ha dues generacions de fitxa: la pilot, escrita a ma, i les que fa el
    script 06 a partir del Cadastre. Aquesta funcio les deixa iguals, aixi no
    cal mantenir dos generadors de PDF.

    Cap camp desconegut s'omple: el que no se sap surt com una linia de punts,
    que es exactament el que ha de veure qui revisi el contracte.
    """
    voc = carregar_vocabulari()
    f = dict(d["finca"])

    # Us cadastral: 'Agrario' -> 'Agrari' si esta tradut.
    if "us" not in f:
        original = f.get("us_catastro", "")
        f["us"] = voc.get("usos", {}).get(original) or original or BUIT

    # Conreus: poden ser diversos, i repetits (una parcel-la amb 4 subparcel-les
    # improductives surt 4 vegades). Els deduplico mantenint l'ordre.
    if "conreu" not in f:
        vistos, llista = set(), []
        for c in f.get("conreus_catastro", []):
            trad = voc.get("conreus", {}).get(c) or c
            if trad not in vistos:
                vistos.add(trad)
                llista.append(trad)
        f["conreu"] = ", ".join(llista) if llista else BUIT

    # La comarca NO la dona el Cadastre. Queda en blanc si ningu l'ha posada.
    f.setdefault("comarca", "")
    if not f["comarca"]:
        f["comarca"] = BUIT

    for clau in ("nom_finca", "terme_municipal", "superficie_ha", "poligon",
                 "parcela", "referencia_cadastral"):
        if not f.get(clau):
            f[clau] = BUIT
    if not f.get("superficie_m2"):
        f["superficie_m2"] = 0
    return f


def normalitza_limits(d):
    """Els limits poden venir com a text o com a llista de referencies.

    El script 06 els calcula a partir de la geometria i en surt una llista de
    referencies cadastrals per cada costat. Aqui es converteixen en text.
    """
    l = {}
    for costat in ("nord", "sud", "est", "oest"):
        v = (d.get("limits") or {}).get(costat, "")
        if isinstance(v, list):
            l[costat] = ", ".join(v) if v else BUIT
        else:
            l[costat] = v if v and v.strip("_ ") else BUIT
    return l


def construir(d):
    """Retorna la llista de blocs (Paragraph/Spacer) que formen el contracte.

    reportlab funciona per 'flowables': una llista de trossos que ell mateix va
    col·locant i paginant. Nosaltres nomes hem de dir QUE va i amb QUIN estil.
    """
    f = normalitza_finca(d)
    l = normalitza_limits(d)
    # Els blocs manuals poden arribar buits (el script 06 no els omple, perque
    # no hi ha cap font publica que els doni). Un camp buit al PDF ha de sortir
    # com una linia de punts, no com un forat: aixi qui revisa el contracte veu
    # que alla falta signar-hi alguna cosa.
    def manual(clau):
        return {k: (v if (v or k.startswith("_")) else BUIT)
                for k, v in (d.get(clau) or {}).items()}

    ce = manual("cedent")
    cs = manual("cessionaria")
    co = manual("coto")
    cn = manual("condicions")

    def b(t):
        """Posa el text en negreta. reportlab accepta mini-HTML dins Paragraph."""
        return "<b>{}</b>".format(t)

    s = []
    A = s.append

    A(Paragraph("CONTRACTE DE CESSIÓ DELS DRETS DE CAÇA D'UNA FINCA", TIT))
    A(Paragraph("A favor d'una associació de caçadors", SUB))
    A(Paragraph("A {}, a {}".format(cn["poblacio"], cn["data"]), P))

    # ---------------- REUNITS ----------------
    A(Paragraph("REUNITS", HC))
    A(Paragraph(
        "D'una part, {}: {}, amb {}, i domicili a efectes de notificacions a {}, que actua en nom propi "
        "en la seva condició de propietari/ària de la finca que es descriu a la Clàusula Primera.".format(
            b("EL/LA CEDENT"), b(ce["nom"]), ce["tipus_document"], ce["adreca"]), P))
    A(Paragraph(
        "I de l'altra, {}: {}, amb NIF {}, i domicili social a {}, inscrita en el {} amb el número {}, "
        "representada en aquest acte per {}, amb {}, en la seva qualitat de {}.".format(
            b("LA CESSIONÀRIA"), b(cs["nom"]), cs["nif"], cs["adreca"], cs["registre"],
            cs["num_registre"], cs["representant"], cs["dni_representant"], cs["carrec"]), P))
    A(Paragraph("Ambdues parts es reconeixen mútuament la capacitat legal necessària per formalitzar el "
                "present contracte i, en conseqüència,", P))

    # ---------------- EXPOSEN ----------------
    A(Paragraph("EXPOSEN", HC))
    # Aquest es l'unic paragraf que s'omple amb dades del Cadastre.
    A(Paragraph(
        "<b>I.</b> Que el/la CEDENT és propietari/ària de la finca coneguda com {}, situada al terme municipal "
        "de {}, comarca de {}, amb una superfície aproximada de {} ({} m²), corresponent al polígon {}, "
        "parcel·la {}, i referència cadastral {}. Ús cadastral: {} ({}).".format(
            b(f["nom_finca"]), b(f["terme_municipal"]), b(f["comarca"]),
            b(f["superficie_ha"] + " ha"), milers(f["superficie_m2"]),
            f["poligon"], f["parcela"], b(f["referencia_cadastral"]), f["us"], f["conreu"]), P))
    A(Paragraph("<b>II.</b> Que la finca descrita reuneix les condicions per a l'exercici de l'activitat "
                "cinegètica, i que el/la CEDENT n'ostenta els drets de caça en plenitud, lliures de càrregues "
                "o cessions anteriors que n'impedeixin la disposició.", P))
    A(Paragraph("<b>III.</b> Que la CESSIONÀRIA és una associació de caçadors legalment constituïda i té "
                "interès a incorporar la finca descrita a l'àmbit territorial del vedat/coto de caça {}, del "
                "qual n'és titular o gestora.".format(b(co["nom_coto"])), P))
    A(Paragraph("<b>IV.</b> Que ambdues parts, de comú acord, formalitzen el present contracte de cessió dels "
                "drets de caça, que se sotmet als següents", P))

    # ---------------- PACTES ----------------
    A(Paragraph("PACTES", HC))

    A(Paragraph("CLÀUSULA PRIMERA. Objecte del contracte", H))
    A(Paragraph("El/la CEDENT cedeix a la CESSIONÀRIA, que ho accepta, el dret d'aprofitament cinegètic (drets "
                "de caça) de la finca descrita en l'expositiu I, perquè aquesta l'incorpori i en gestioni la "
                "pràctica de la caça d'acord amb la normativa vigent i el pla d'aprofitament cinegètic "
                "aplicable.", P))

    A(Paragraph("CLÀUSULA SEGONA. Descripció i delimitació de la finca", H))
    A(Paragraph("La finca objecte de cessió té els següents límits: al nord amb {}; al sud amb {}; a l'est amb "
                "{}; i a l'oest amb {}. S'adjunta com a Annex I plànol de situació i delimitació de la finca, "
                "obtingut de la cartografia cadastral oficial.".format(
                    l["nord"], l["sud"], l["est"], l["oest"]), P))

    A(Paragraph("CLÀUSULA TERCERA. Durada", H))
    A(Paragraph("El present contracte tindrà una durada de {}, des de la temporada cinegètica {} fins a la "
                "temporada {}, prorrogable tàcitament per períodes anuals successius llevat que qualsevol de "
                "les parts en comuniqui la no renovació amb una antelació mínima de {} abans de la finalització "
                "de cada temporada.".format(cn["durada_anys"], cn["temporada_inici"],
                                            cn["temporada_fi"], cn["preavis"]), P))

    A(Paragraph("CLÀUSULA QUARTA. Contraprestació", H))
    A(Paragraph("La cessió es realitza {}. En cas de contraprestació econòmica, aquesta es farà efectiva {}, "
                "mitjançant {}.".format(b(cn["contraprestacio"]), cn["forma_pagament"],
                                        cn["mitja_pagament"]), P))

    A(Paragraph("CLÀUSULA CINQUENA. Obligacions del/de la cedent", H))
    for t in [
        "Garantir a la CESSIONÀRIA el gaudi pacífic dels drets de caça cedits durant tota la vigència del "
        "contracte.",
        "No exercir per si mateix/a ni autoritzar a tercers l'exercici de la caça a la finca durant la "
        "vigència del contracte, llevat del que es pacti expressament a la Clàusula Sisena.",
        "Comunicar a la CESSIONÀRIA qualsevol circumstància que pugui afectar l'exercici normal de la caça a "
        "la finca (obres, tancaments, canvis de titularitat, etc.).",
    ]:
        A(Paragraph(t, LI, bulletText="•"))

    A(Paragraph("CLÀUSULA SISENA. Obligacions de la cessionària", H))
    for t in [
        "Exercir l'activitat cinegètica d'acord amb la legislació de caça vigent, el pla tècnic de gestió "
        "cinegètica i les autoritzacions administratives corresponents.",
        "Respectar els conreus, tanques, camins, edificacions i altres béns existents a la finca, i respondre "
        "dels danys que es puguin ocasionar per l'exercici de la caça.",
        "Disposar de les assegurances obligatòries de responsabilitat civil de caça que cobreixin els danys a "
        "persones o béns derivats de l'activitat cinegètica.",
        "Facilitar al/a la CEDENT, si ho sol·licita, un o diversos permisos de caça anuals a la finca, en els "
        "termes que es pactin.",
        "Respectar l'accés del/de la CEDENT i dels seus familiars i treballadors a la finca en tot moment.",
    ]:
        A(Paragraph(t, LI, bulletText="•"))

    A(Paragraph("CLÀUSULA SETENA. Responsabilitat civil i assegurances", H))
    A(Paragraph("La CESSIONÀRIA es compromet a mantenir en vigor, durant tota la durada del contracte, una "
                "pòlissa d'assegurança de responsabilitat civil que cobreixi els danys a persones i béns que "
                "es puguin derivar de l'exercici de la caça a la finca, eximint expressament al/a la CEDENT de "
                "qualsevol responsabilitat derivada d'aquesta activitat.", P))

    A(Paragraph("CLÀUSULA VUITENA. Prohibicions", H))
    A(Paragraph("Queda expressament prohibit a la CESSIONÀRIA subarrendar, cedir o transmetre a tercers, "
                "totalment o parcialment, els drets objecte d'aquest contracte sense el consentiment exprés i "
                "per escrit del/de la CEDENT.", P))

    A(Paragraph("CLÀUSULA NOVENA. Resolució del contracte", H))
    A(Paragraph("El present contracte es podrà resoldre anticipadament per: a) mutu acord de les parts; "
                "b) incompliment greu de qualsevol de les obligacions pactades; c) pèrdua de la condició de "
                "titular de la finca per part del/de la CEDENT; o d) dissolució de la CESSIONÀRIA. En qualsevol "
                "dels supòsits anteriors, la part que incompleixi haurà de respondre dels danys i perjudicis "
                "que la seva actuació pugui ocasionar a l'altra part.", P))

    A(Paragraph("CLÀUSULA DESENA. Protecció de dades", H))
    A(Paragraph("Les dades personals facilitades per les parts en el present contracte seran tractades d'acord "
                "amb el Reglament (UE) 2016/679 (RGPD) i la normativa vigent en matèria de protecció de dades, "
                "amb l'única finalitat de gestionar la relació contractual derivada d'aquest document.", P))

    A(Paragraph("CLÀUSULA ONZENA. Legislació aplicable i jurisdicció", H))
    A(Paragraph("Aquest contracte es regeix per la legislació de caça de Catalunya (Llei 1/1970, de caça, i "
                "normativa de desplegament) i pel Codi Civil de Catalunya en tot allò no previst expressament. "
                "Per a la resolució de qualsevol controvèrsia derivada d'aquest contracte, les parts se sotmeten "
                "als Jutjats i Tribunals de {}, amb renúncia expressa a qualsevol altre fur que els pogués "
                "correspondre.".format(cn["partit_judicial"]), P))

    # ---------------- SIGNATURES ----------------
    A(Spacer(1, 14 * mm))
    A(Paragraph("{}<br/><br/>Signat: ______________________________<br/>{}".format(
        b("EL/LA CEDENT"), ce["nom"]), SIG))
    A(Spacer(1, 8 * mm))
    A(Paragraph("{}<br/><br/>Signat: ______________________________<br/>{}, {}".format(
        b("LA CESSIONÀRIA"), cs["representant"], cs["carrec"]), SIG))

    A(Paragraph("Aquest document és un model genèric orientatiu. Es recomana la seva revisió per un/a advocat/da "
                "abans de la seva signatura, especialment pel que fa a la descripció registral/cadastral de la "
                "finca, la normativa cinegètica autonòmica aplicable i les condicions fiscals de la "
                "contraprestació, si escau. Dades cadastrals obtingudes de la Seu Electrònica del Cadastre "
                "(Direcció General del Cadastre): superfície cadastral, no registral.", NOTA))
    return s


def generar(ruta_json, carpeta_sortida="salidas"):
    """Llegeix el JSON, construeix el document i el desa com a PDF."""
    with open(ruta_json, encoding="utf-8") as fh:
        d = json.load(fh)

    rc = d["finca"]["referencia_cadastral"]
    os.makedirs(carpeta_sortida, exist_ok=True)
    desti = os.path.join(carpeta_sortida, "contracte_cessio_caca_{}.pdf".format(rc))

    # SimpleDocTemplate = el "full" on anira tot: mida A4 i marges en mil·limetres.
    doc = SimpleDocTemplate(
        desti, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="Contracte cessio drets de caca - {}".format(rc),
        author="Cessio de drets de caca",
    )
    doc.build(construir(d))   # aqui es on realment s'escriu el PDF
    print("Generat:", desti)
    return desti


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Us: python scripts/03_generar_contracte.py <ruta_json>")
        sys.exit(1)
    generar(sys.argv[1])
