# Confidentialité et protection des données

> Ce document décrit ce que fait **le logiciel**. Ce n'est pas un avis juridique : la conformité RGPD d'un service dépend aussi de son usage (voir « Ce que le logiciel ne peut pas faire »).

## Ce qui est stocké
| Donnée | Où | Protection |
|---|---|---|
| Identifiant (pseudo), date de création, dernière connexion | table `users`, en clair | aucune donnée d'identité réelle demandée (pas d'e-mail, pas de nom) |
| Empreinte du mot de passe | table `users` | scrypt (salé, coûteux), jamais le mot de passe |
| Positions, ordres, ventes (avec commission), livrets, crypto et matières premières, réglages, répartition cible | table `records`, **un blob chiffré par enregistrement** | AES-256-GCM avec la clé de l'utilisateur |
| Données de marché (écarts d'ouverture, cache) | tables `gap_log`, `cache_store` | ne contiennent aucune donnée personnelle |

## Qui peut créer un compte
La création de compte exige un **code** : le code d'inscription commun (`SIGNUP_CODE`) ou une invitation à usage unique générée par l'administrateur. Sans code valide, personne ne peut s'inscrire (y compris le premier compte quand `SIGNUP_CODE` est défini). Les essais sont limités.

## Comment le chiffrement fonctionne
- À l'inscription, une **clé de données** aléatoire de 256 bits est créée pour l'utilisateur. Elle n'est stockée que **chiffrée** : une fois avec son mot de passe, une fois avec sa **clé de récupération**.
- Le mot de passe n'est jamais stocké ; la clé qui ouvre la clé de données est recalculée à chaque connexion (scrypt).
- Chaque blob est lié à son propriétaire (données authentifiées) : le déplacer chez un autre utilisateur le rend illisible.
- La clé de données n'existe en clair qu'en **mémoire du serveur**, pendant la session (60 min d'inactivité, 12 h maximum). Elle n'est jamais écrite sur le disque.

**Conséquences** : une copie volée de la base ou une sauvegarde de la machine ne révèle aucune donnée financière. L'administrateur (qui gère les comptes) ne peut **pas** lire les données des autres. **Mot de passe oublié + clé de récupération perdue = données définitivement perdues** (il n'existe aucune porte dérobée).

## Droits des personnes (implémentés)
- **Accès / portabilité** : *Mon compte → Télécharger mes données* (JSON complet).
- **Effacement** : *Mon compte → Supprimer mon compte et mes données* (confirmation par mot de passe) ; l'administrateur peut aussi supprimer un compte.
- **Rectification** : toutes les données sont modifiables depuis l'interface.
- **Minimisation** : aucun e-mail, aucun nom, aucun traceur, aucun service d'analyse tiers.
- **Sécurité des accès** : limitation des tentatives de connexion, sessions à durée limitée, cookies HttpOnly + SameSite=Strict (+ Secure en HTTPS), protection CSRF, en-têtes de sécurité, pas de mise en cache des réponses.

## Ce qui sort du serveur
Pour calculer les cours, le serveur interroge Boursorama, Yahoo Finance, Google (actualités) et JustETF avec des **symboles boursiers** (ex. « WPEA.PA »), depuis l'adresse IP du serveur et **sans identifier l'utilisateur**. Les symboles consultés peuvent apparaître dans les journaux du serveur.

## Ce que le logiciel ne peut pas faire
- Le serveur **déchiffre vos données en mémoire** pendant que vous êtes connecté pour calculer vos chiffres : quelqu'un qui contrôlerait la machine **en direct** pourrait les voir. Le chiffrement protège « au repos » (disque, sauvegardes, administrateur), pas contre une machine compromise en fonctionnement.
- L'identifiant et les dates de connexion restent visibles de l'administrateur.
- Le RGPD ne se résume pas à la technique. Un usage **strictement personnel ou familial** relève généralement de l'exception domestique ; si vous proposez le service à d'autres personnes de façon plus large, il faut en plus : une information claire des utilisateurs (finalités, durée de conservation, droits, contact), une base légale, le cas échéant un registre des traitements, une procédure en cas de violation de données (notification à la CNIL sous 72 h si nécessaire), et la sécurité du reste de l'infrastructure (HTTPS, mises à jour, accès à Proxmox, chiffrement des sauvegardes). En cas de doute, consultez la CNIL ou un juriste.
