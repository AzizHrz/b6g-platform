# Concept Beyond 6G (B6G) — note de cadrage (T01.1)

Réalisme : **DOCUMENTAIRE**. Les gammes chiffrées citées sont des objectifs de recherche issus des documents de
référence, pas des mesures de la plateforme.

## 1. De quoi parle-t-on

La 6G désigne la génération de réseaux mobiles visée pour 2030 et au-delà, encadrée par l'UIT sous le nom
**IMT-2030** (Recommandation UIT-R M.2160). Le terme **Beyond 6G (B6G)** regroupe, dans ce projet, les capacités qui
prolongent cette vision : réseau **intelligent** (IA native), **autonome** (boucles fermées sans intervention),
**distribué** (continuum Edge / Fog / Cloud, segments non terrestres) et **durable** (énergie comme objectif de
pilotage). Le sous-titre de l'atelier 28 reprend ces quatre qualificatifs.

La plateforme du projet émule ces concepts sur un socle 5G autonome réel (Open5GS + UERANSIM) : chaque atelier ajoute
une brique, et chaque résultat porte une étiquette de réalisme (RÉEL, ÉMULÉ, SIMULÉ, SYNTHÉTIQUE, MAQUETTE).

## 2. Évolutions de la 6G vers le B6G

| # | Évolution | Ce qui change | Source | Ateliers du projet |
| --- | --- | --- | --- | --- |
| 1 | **IA native** dans le réseau | L'IA devient une fonction du réseau (scénario « AI and communication ») et non un outil externe ; cycle de vie des modèles dans le réseau | UIT-R M.2160 (2023), scénarios d'usage ; UIT-T Y.3172 (cadre ML pour les réseaux futurs) | 11, 18, 19, 23, 24 |
| 2 | **Réseau autonome** (zero-touch) | Boucles fermées surveiller / analyser / décider / agir, intent-based management | ETSI GS ZSM 002 (architecture de référence ZSM) | 6, 26 |
| 3 | **Slicing dynamique** de bout en bout | Tranches créées, dimensionnées et réajustées automatiquement selon des SLA | 3GPP TS 23.501 (S-NSSAI, sélection de slice) ; ETSI ZSM | 4, 6 |
| 4 | **Communication et détection intégrées (ISAC)** | Le réseau détecte et localise en plus de communiquer | UIT-R M.2160 (scénario « Integrated sensing and communication ») ; 3GPP TR 22.837 (étude ISAC, Rel-19) | 15 |
| 5 | **Connectivité ubiquitaire et réseaux non terrestres (NTN)** | Intégration des satellites et plateformes aériennes au réseau mobile | UIT-R M.2160 (scénario « Ubiquitous connectivity ») ; 3GPP Rel-17/18 (NTN) | 14, 17 |
| 6 | **Continuum Edge / Fog / Cloud** et réseau cloud-native | Fonctions réseau et applications placées dynamiquement selon la latence et la charge | ETSI GS NFV 002 (cadre NFV) ; ETSI MEC ; principes cloud-native (Kubernetes) | 7, 8, 9, 10, 12 |
| 7 | **RAN ouvert et programmable** | Contrôleurs RIC (temps quasi réel / non temps réel) et applications xApp / rApp | Spécifications de l'O-RAN Alliance (architecture WG1, RIC) | 16 |
| 8 | **Jumeau numérique du réseau** | Évaluer une décision sur une réplique avant de l'appliquer (what-if) | Hexa-X, livrable D1.2 (vision 6G et cas d'usage, 2021) ; UIT-T Y.3090 (jumeau numérique de réseau) | 20, 26 |
| 9 | **Durabilité énergétique** comme objectif | Énergie mesurée et pilotée (mise en veille, consolidation) au même titre que la QoS | UIT-R M.2160 (durabilité parmi les principes) ; 3GPP Rel-18 (économies d'énergie réseau) | 25 |
| 10 | **Confiance, sécurité et traçabilité** | Sécurité pilotée par l'IA, registres distribués pour l'auditabilité des actions | UIT-R M.2160 (sécurité et résilience) ; Hexa-X D1.2 (valeurs : confiance) | 21, 27 |
| 11 | **Communications véhiculaires exigeantes (V2X)** | Latence et fiabilité élevées pour la conduite coopérative ; exigences de cybersécurité réglementées | 3GPP TS 22.186 (exigences eV2X) ; règlements ONU R155 (cybersécurité) et R156 (mises à jour logicielles) | 13, fil rouge (slice v2x) |
| 12 | **Optimisation quantique et hybride** | Approches quantiques pour des problèmes d'allocation combinatoires | Travaux de recherche en cours (aucune norme) ; outils Qiskit | 22 |

Gammes d'objectifs IMT-2030 (UIT-R M.2160, valeurs de recherche indicatives) : débit crête de 50 à 200 Gbit/s,
latence de 0,1 à 1 ms, densité de connexions de 10⁶ à 10⁸ appareils par km², précision de positionnement de 1 à 10 cm.
La plateforme du projet ne vise pas ces valeurs (pas de couche radio) : elle reproduit les **mécanismes** de gestion.

## 3. Correspondance avec le fil rouge

Le « corridor urbain connecté » du projet met en œuvre ces évolutions sur trois slices :

| Slice | Service | Évolutions mobilisées |
| --- | --- | --- |
| `embb` (SST 1) | vidéo et services aux passagers | 3, 6, 9 |
| `v2x` (SST 4) | messages coopératifs des véhicules | 2, 3, 11 |
| `miot` (SST 3) | capteurs de bord de route et drones | 4, 5, 9 |

## 4. Acquis du projet 6G repris

Le plan prévoit de partir des acquis du projet 6G précédent. Inventaire à compléter à partir de son rapport :

| Acquis | Origine (livrable du projet 6G) | Réutilisation dans B6G |
| --- | --- | --- |
| *à compléter* | | |

Acquis techniques déjà réutilisés par le socle B6G (indépendamment du projet 6G) : cœur 5G autonome Open5GS,
simulateur RAN UERANSIM, slicing par S-NSSAI, observabilité Prometheus / Grafana.
