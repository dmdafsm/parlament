"""Learning pages: what MPs do and how a law is made. Static content, reviewed against the Constitution."""

PAGES = {
    "rolul-parlamentului": {
        "icon": "account_balance",
        "title": "Rolul Parlamentului",
        "body": """
<p>Parlamentul este organul reprezentativ suprem al poporului român și unica autoritate legiuitoare a țării
(art. 61 din Constituție). Este format din două camere: <b>Camera Deputaților</b> și <b>Senatul</b>, alese pentru
patru ani prin vot universal, egal, direct, secret și liber exprimat.</p>
<h6>Ce face Parlamentul</h6>
<ul>
  <li><b>Adoptă legi</b>: constituționale, organice și ordinare.</li>
  <li><b>Controlează Guvernul</b>: îi acordă votul de încredere la învestire, îi adresează întrebări și interpelări,
  poate adopta moțiuni simple și îl poate demite prin moțiune de cenzură.</li>
  <li><b>Aprobă bugetul de stat</b> și bugetul asigurărilor sociale.</li>
  <li><b>Numește</b> conducerea unor instituții (de exemplu, Avocatul Poporului, o parte din judecătorii Curții Constituționale).</li>
  <li><b>Declară mobilizarea</b> și starea de război, aprobă starea de urgență sau de asediu instituită de Președinte.</li>
</ul>
<h6>Legislatura 2024–2028</h6>
<p>Parlamentul actual a fost ales la 1 decembrie 2024: 331 de deputați și 134 de senatori. România are 43 de circumscripții
electorale: cele 41 de județe, municipiul București și circumscripția pentru românii din afara țării (Diaspora).
Organizațiile minorităților naționale care nu obțin mandate în mod obișnuit primesc câte un mandat de deputat.</p>
""",
    },
    "deputati-si-senatori": {
        "icon": "badge",
        "title": "Ce fac deputații și senatorii",
        "body": """
<p>Deputații și senatorii au același statut (Legea nr. 96/2006). Mandatul lor este <b>reprezentativ</b>: sunt în serviciul
poporului, iar orice mandat imperativ (instrucțiuni obligatorii de la partid sau alegători) este nul (art. 69 din Constituție).</p>
<h6>Activitatea în plen</h6>
<ul>
  <li><b>Votează</b> legile, hotărârile și moțiunile. La Camera Deputaților votul electronic este public, nominal.</li>
  <li><b>Iau cuvântul</b> în dezbateri, fac declarații politice.</li>
  <li><b>Inițiază legi</b>: orice deputat sau senator poate depune o propunere legislativă.</li>
</ul>
<h6>Controlul Guvernului</h6>
<ul>
  <li><b>Întrebări</b>: cereri de informații adresate unui ministru sau Guvernului, cu răspuns scris sau oral.</li>
  <li><b>Interpelări</b>: cereri prin care se solicită explicații despre politica Guvernului într-o problemă importantă.</li>
  <li><b>Moțiuni</b>: simple (exprimă poziția unei camere) sau de cenzură (pot demite Guvernul, în ședință comună).</li>
</ul>
<h6>Comisiile</h6>
<p>Cea mai mare parte a muncii pe legi se face în comisiile permanente (buget, juridică, sănătate etc.): acolo se dezbat
amendamentele și se întocmesc rapoartele pe care le votează apoi plenul.</p>
<h6>În circumscripție</h6>
<p>Fiecare parlamentar are birouri parlamentare în circumscripția în care a fost ales, unde cetățenii pot depune
sesizări și cereri. Adresele sunt publicate pe profilul oficial.</p>
<h6>Obligații</h6>
<ul>
  <li>Să participe la lucrările camerei și ale comisiilor; absențele nemotivate pot fi sancționate conform regulamentelor.</li>
  <li>Să depună <b>declarații de avere și de interese</b> la începutul și la sfârșitul mandatului și anual.</li>
  <li>Să respecte regimul incompatibilităților și conflictelor de interese.</li>
</ul>
""",
    },
    "cum-se-face-o-lege": {
        "icon": "gavel",
        "title": "Cum se face o lege",
        "body": """
<ol>
  <li><b>Inițiativa.</b> Pot propune legi Guvernul (<i>proiecte de lege</i>), deputații și senatorii (<i>propuneri legislative</i>)
  și cel puțin 100.000 de cetățeni cu drept de vot (art. 74).</li>
  <li><b>Avize.</b> Consiliul Legislativ avizează toate inițiativele; după caz, și Consiliul Economic și Social sau Guvernul.</li>
  <li><b>Prima cameră sesizată.</b> Depinde de domeniu (art. 75): pentru multe legi Senatul este prima cameră, pentru altele
  Camera Deputaților. Prima cameră are 45 de zile (60 pentru coduri și legi complexe) să se pronunțe; altfel proiectul
  se consideră <b>adoptat tacit</b>.</li>
  <li><b>Comisiile</b> analizează proiectul, votează amendamente și depun un raport (favorabil sau de respingere).</li>
  <li><b>Plenul</b> dezbate și votează. Legile organice au nevoie de majoritatea membrilor camerei, cele ordinare de
  majoritatea celor prezenți.</li>
  <li><b>Camera decizională</b> se pronunță definitiv; dacă modifică o prevedere care era de competența primei camere,
  legea se întoarce la aceasta.</li>
  <li><b>Controlul de constituționalitate.</b> Înainte de promulgare, legea poate fi atacată la Curtea Constituțională de
  Președinte, de președinții camerelor, de Guvern, de ÎCCJ, de Avocatul Poporului sau de 50 de deputați / 25 de senatori.</li>
  <li><b>Promulgarea.</b> Președintele promulgă legea în 20 de zile; o poate retrimite o singură dată Parlamentului spre reexaminare.</li>
  <li><b>Publicarea</b> în Monitorul Oficial; legea intră în vigoare la 3 zile de la publicare sau la data prevăzută în text.</li>
</ol>
<p>Pe pagina fiecărui proiect de pe acest site vezi pașii parcurși, cu datele și documentele oficiale.</p>
""",
    },
    "ordonante": {
        "icon": "bolt",
        "title": "Ordonanțele Guvernului",
        "body": """
<p>Guvernul poate emite acte cu putere de lege, numite ordonanțe (art. 115 din Constituție):</p>
<ul>
  <li><b>Ordonanțe simple (OG)</b>, doar în baza unei legi speciale de abilitare, de obicei în vacanța parlamentară,
  și doar în domenii care nu fac obiectul legilor organice.</li>
  <li><b>Ordonanțe de urgență (OUG)</b>, numai în situații extraordinare a căror reglementare nu poate fi amânată.
  Intră în vigoare după depunerea la Parlament și publicarea în Monitorul Oficial.</li>
</ul>
<p>Parlamentul trebuie apoi să aprobe sau să respingă fiecare ordonanță prin lege. Dacă prima cameră nu se pronunță în 30 de
zile, OUG se consideră adoptată de aceasta. Folosirea frecventă a ordonanțelor de urgență mută o parte din puterea de a
legifera de la Parlament la Guvern; pagina <a class="link" href="/ordonante">Ordonanțe</a> arată câte sunt și cât durează aprobarea lor.</p>
""",
    },
    "glosar": {
        "icon": "menu_book",
        "title": "Glosar",
        "body": """
<dl>
  <dt><b>Biroul permanent</b></dt><dd>Organul de conducere al fiecărei camere (președinte, vicepreședinți, secretari, chestori).</dd>
  <dt><b>Cameră decizională</b></dt><dd>Camera care adoptă definitiv un proiect, după ce prima cameră s-a pronunțat.</dd>
  <dt><b>Grup parlamentar</b></dt><dd>Asocierea parlamentarilor aleși pe listele aceluiași partid (minimum 10 deputați / 7 senatori).</dd>
  <dt><b>Neafiliat</b></dt><dd>Parlamentar care nu face parte din niciun grup parlamentar.</dd>
  <dt><b>Lege organică / ordinară</b></dt><dd>Legile organice reglementează domenii prevăzute de Constituție și se adoptă cu majoritatea membrilor; cele ordinare, cu majoritatea celor prezenți.</dd>
  <dt><b>PL-x, Pl-x, BP</b></dt><dd>Prefixe din registrul Camerei Deputaților: PL-x pentru proiecte și propuneri de lege aflate în procedură, BP pentru înregistrarea la Biroul permanent.</dd>
  <dt><b>Procedură de urgență</b></dt><dd>Dezbatere accelerată, cu termene mai scurte pentru avize și rapoarte.</dd>
  <dt><b>Stenogramă</b></dt><dd>Transcrierea integrală a dezbaterilor din plen.</dd>
  <dt><b>Traseism politic</b></dt><dd>Termen folosit pentru schimbarea partidului sau a grupului parlamentar în timpul mandatului.</dd>
  <dt><b>Vot nominal</b></dt><dd>Lista care arată cum a votat fiecare parlamentar prezent.</dd>
</dl>
""",
    },
}
