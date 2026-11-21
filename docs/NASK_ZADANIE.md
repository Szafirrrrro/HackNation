# The Kolekcjoner Fejków

Źródłem transkrypcji jest dokument NASK „Pełna treść zadania konkursowego” przygotowany na HackNation 2026.

## Follow the Fake

> “Matrix jest wszędzie, otacza nas ze wszystkich stron. Nawet tu i teraz. Widzisz go wyglądając przez okno i włączając telewizor. Czujesz, gdy idziesz do pracy, czy do kościoła, gdy płacisz podatki. To świat, który postawiono ci przed oczami, by przesłonić prawdę.”
>
> — Morfeusz, Matrix

Społeczeństwo przyzwyczajone jest do tego, że to, co zobaczą na ekranie jest prawdziwe. To jest nasz Matrix - nie wiemy, gdzie jest granica między prawdą, a kłamstwem. Często bywamy rozbrajani z ostrożności przez ładne, spreparowane reklamy, kolorowe filmiki, albo obietnice potwierdzone przez dziesiątki osób. Gdy jednak zanurzymy się w świat kłamstwa, możemy znaleźć pewne zależności, a może nawet dotrzeć do ich źródła.

Twoim przeznaczeniem jest wzięcie udziału w wojnie z kłamstwem, którym cały czas jesteśmy bombardowani. Wspólnie musimy wejść w posiadanie narzędzi, które w jasny sposób oddzielą prawdę od oszustwa w świecie po drugiej stronie ekranu. Każdy powinien czuć się bezpiecznie we wspólnej przestrzeni - nie tylko tej fizycznej, ale i wirtualnej. A przecież żyjemy w świecie, w którym świat wirtualny wpływa na prawdziwy. Fałszywe wypowiedzi polityków, nieprawdziwe wypowiedzi lekarzy, narracje budujące nienawiść do różnych grup społecznych przekładają się na prawdziwe zachowania. Zadaniem jest znaleźć metodę, która z chaosu pojedynczych reklam wyciągnie strukturę. Rozpoznajcie cechy wspólne, określcie podobieństwo i połączcie materiały należące do tych samych lub podobnych kampanii.

Na fałszywe materiały najczęściej możemy natknąć się w mediach społecznościowych oraz portalach o charakterze rozrywkowym. Musimy posiąść wiedzę, jak dostać się do bibliotek takich reklam, aby przeprowadzić ich pełną analizę. Pomoże nam to w pozyskaniu informacji o źródle fałszu i jego wyeliminowaniu.

Reklamy zwykle tworzone są na domenach o krótkim czasie życia, ale mogą współdzielić między sobą inne metadane. Po pozyskaniu materiału możemy sprawdzić informacje o domenie, ewentualne przekierowania, odnośniki, motyw przewodni, słowa kluczowe, wykorzystane wizerunki osób.

Dysponując m.in takimi informacjami możemy stworzyć system grupowania kampani reklamowych. Kluczowa jest wiedza o tym, jak skutecznie łączyć reklamy o podobnych cechach: wizualnych, semantycznych, konceptualnych i wielu innych. Klaster może powstać z różnych powodów. Reklamy mogą wykorzystywać podobną narrację (tekst), te same osoby, podobny szablon produkcji, wspólną domenę albo zestaw innych pozornie drobnych sygnałów, które pojedynczo wydają się nieistotne, lecz razem wskazują na jedno źródło. Taka wiedza pozwala identyfikować wzorce wspólne dla różnych kampanii i wykorzystywać je do szybszego wykrywania nowych odsłon tych samych fałszywych narracji. Gdy kolejne warianty można powiązać ze wspólnym źródłem i mechanizmem działania, iluzja informacyjnego Matrixa zaczyna się rozpadać.

> “Umiesz tym latać?”
>
> — Neo, Matrix (fragment dialogu)

## Kwestie techniczne

Przejdźmy do kwestii technicznych. Bo po to tu jesteśmy.

- Rozwiązanie powinno zawierać prosty demonstrator (prosta stronka, np. z wykorzystaniem Streamlit, Gradio, lub innych; jej estetyka nie podlega ocenie. Jest oceniana 0/1 - jest, albo jej nie ma. Chodzi tylko o to, aby mieć graficzne środowisko uruchomieniowe). Strona może przyjąć bezpośredni adres URL, zrzut ekranu zawierający link, lub inną wskazówkę jak nazwa produktu, albo plik zawierający podejrzaną reklamę, aby uruchomić proces analizy. Dodatkowym, pozytywnym akcentem może być zaszyty scheduler, który samodzielnie wykonuje skan zidentyfikowanych bibliotek reklam, znajduje te podejrzane i wykonuje ich analizy.
- Zakres analizy jest dowolny. Ocenie podlegają mechanizmy i ich przydatność w kontekście zadania. Przykład: słowa kluczowe z tekstu, najważniejsze elementy wizualne, wyizolowane strony internetowe, metadane tych stron.
- Sposób identyfikacji podobieństwa jest dowolny. Może to być podobieństwo ważone, może drobny model, a może jakiś silnik klastrujący. Zdaj się na swoją wiedzę. Skup się. Jest to jeden z kluczowych elementów zadania.
- Jak wyciągnąć tożsamość osoby widocznej na materiale? Dowolnie. Sugeruję zrobić wstępną bazę referencyjną kilku, najczęściej występujących osób. Obszerność tej bazy jest nieistotna. Ma tylko przyczynić się do udowodnienia użyteczności narzędzia.
- Reprezentacja powiązań? Zdaj się na swoją wiedzę. Może Neo4j?

Nie chodzi o stworzenie idealnego detektora pojedynczej fałszywej reklamy. Zbudujcie sposób na okrywanie, jak skutecznie łączyć wiele pozornie niezależnych materiałów w większe kampanie na podstawie pozostawianych przez nie wspólnych śladów.

PS. Widział_ś stronę z zajawką? <https://science.nask.pl/hacknation>

Adres z kodu QR obok napisu „Zeskanuj mnie”: <https://loyalty.nuvio.group/enroll/6586110843755849>
