# Déploiement de Némésis sur un VPS (AWS Lightsail)

Faire tourner le bot **24/7** sur une petite VM Linux **AWS Lightsail**, avec
redémarrage automatique (systemd) et consultation des stats depuis Windows via
**tunnel SSH** (rien n'est exposé sur Internet : seul le port 22 est ouvert).

```
Discord ⇄  bot (VM Lightsail, systemd)  ──▶  data/stats.db  ──▶  API JSON 127.0.0.1:8787
                                                                       │
   PC Windows : tunnel SSH  ssh -L 8787:127.0.0.1:8787  ──────────────┘
                        puis app bureau (desktop/) → lit localhost:8787
```

> 💰 **Coût.** Contrairement à Oracle « Always Free », Lightsail est **payant**
> mais à **prix fixe** : le plan retenu (**5 $/mois**, 1 Go RAM, 2 vCPU, 40 Go SSD,
> 2 To de transfert inclus) suffit très largement pour le bot. Le plan 3,50 $
> (512 Mo) marche aussi mais peut être juste pendant `uv sync` — on peut
> redimensionner plus tard sans réinstaller.

> ⚠️ **Clé Riot.** Une clé de **développement expire toutes les 24 h** → le bot
> renverrait des 403 chaque jour. Pour un bot permanent, demander une **Personal
> API Key** (persistante) sur <https://developer.riotgames.com/> (section
> *Register Product* / *Personal API Key*). Voir aussi les « 3 pièges » du CLAUDE.md.

---

## 1. Créer l'instance Lightsail

1. Compte sur <https://aws.amazon.com/> puis ouvrir la **console Lightsail**
   (<https://lightsail.aws.amazon.com/>). Carte bancaire requise **et facturée**
   (≈ 5 $/mois).
2. **Create instance** :
   - **Region / Availability Zone** : la plus proche (p. ex. `eu-west-3`, Paris).
   - **Platform** : *Linux/Unix*.
   - **Blueprint** : *OS Only* → **Ubuntu 24.04 LTS**.
   - **SSH key pair** : *Change SSH key pair* → **Upload new** et téléverser ta clé
     publique (`~/.ssh/id_ed25519.pub`). Sinon en générer une : `ssh-keygen -t ed25519`.
     (À défaut, Lightsail génère une clé `.pem` à télécharger — mais uploader la
     tienne garde le même flux SSH que le reste de la doc.)
   - **Instance plan** : **5 $/mois** (1 Go RAM). Le 3,50 $ (512 Mo) convient aussi.
   - **Nommer** l'instance (p. ex. `nemesis`) puis **Create instance**.
3. **IP statique** (indispensable : sinon l'IP publique change à chaque stop/start) :
   onglet **Networking** de l'instance → **Create static IP** → l'attacher à
   l'instance. Noter cette IP.
4. **Pare-feu** : Lightsail ouvre **SSH (22)** par défaut. **Ne pas** ajouter de règle
   pour le port 8787 : le tunnel SSH suffit et garde l'API privée.

Se connecter (utilisateur par défaut d'Ubuntu sur Lightsail = `ubuntu`) :

```bash
ssh ubuntu@<IP_STATIQUE>
```

---

## 2. Préparer le serveur

```bash
# Outils de base + git
sudo apt update && sudo apt install -y git

# uv (installe et gère Python 3.14 tout seul — pas besoin d'un Python système)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc            # pour avoir uv dans le PATH

# Récupérer le projet
git clone https://github.com/Noetflix/Nemesis.git ~/nemesis
cd ~/nemesis
uv sync                     # crée le venv + installe les dépendances

# Configurer les secrets
cp .env.example .env
nano .env                   # DISCORD_TOKEN + RIOT_API_KEY (clé Personal !) obligatoires
```

Laisser `STATS_API_HOST=127.0.0.1` dans le `.env` (défaut) : l'API reste locale,
on y accède par tunnel SSH.

Test rapide avant de « systemd-iser » (Ctrl-C pour arrêter) :

```bash
uv run python -m nemesis
```

---

## 3. Lancer en service systemd (démarrage auto + relance sur crash)

L'unit fournie suppose l'utilisateur `ubuntu` et le dépôt dans `/home/ubuntu/nemesis`
(adapter le fichier sinon).

```bash
# Vérifier le chemin réel de uv et l'ajuster dans l'unit si besoin :
which uv                    # attendu : /home/ubuntu/.local/bin/uv

sudo cp ~/nemesis/deploy/nemesis.service /etc/systemd/system/nemesis.service
sudo systemctl daemon-reload
sudo systemctl enable --now nemesis      # démarre + active au boot

# Vérifs
systemctl status nemesis
journalctl -u nemesis -f                 # logs en direct (Ctrl-C pour quitter)
```

---

## 4. Consulter les stats depuis Windows (tunnel SSH)

Le serveur JSON écoute sur `127.0.0.1:8787` **sur la VM**. On le rapatrie en local :

```powershell
# Dans un terminal Windows — laisser ouvert le temps de consulter les stats
ssh -N -L 8787:127.0.0.1:8787 ubuntu@<IP_STATIQUE>
```

Puis lancer l'app bureau **sans aucune config** : son URL par défaut est déjà
`http://127.0.0.1:8787`, que le tunnel redirige vers la VM.

```powershell
# depuis F:\nemesis
uv run --group desktop python desktop/app.py
# …ou le raccourci Nemesis-Stats.exe si tu l'as construit
```

Fermer le terminal du tunnel coupe l'accès (l'API reste injoignable autrement).

---

## 5. Mettre à jour le bot

**Manuellement**, en SSH sur la VM :

```bash
cd ~/nemesis
git pull
uv sync                         # au cas où des dépendances changent
sudo systemctl restart nemesis
```

**Automatiquement** (recommandé) via GitHub Actions : un merge sur `main` déclenche
un déploiement gaté par une validation manuelle (SSH → `git reset --hard` + `uv sync`
+ redémarrage du service). Configuration complète dans **`deploy/CICD.md`**.

---

## Dépannage

| Symptôme | Piste |
| --- | --- |
| `403` de l'API Riot dans les logs | Clé expirée (dev = 24 h) → clé **Personal**. |
| Le bot ne lit pas les commandes | Intent **Message Content** à activer (portail Discord). |
| `systemctl status` : `uv: not found` | Corriger le chemin `ExecStart` (voir `which uv`). |
| Tunnel OK mais app vide | Vérifier `systemctl status nemesis` et `STATS_ENABLED=1`. |
| L'IP a changé après un redémarrage | IP statique non attachée (voir §1.3) — rattacher une *static IP*. |
| `uv sync` tué (OOM) sur le plan 512 Mo | Passer au plan 1 Go (5 $) : *Instance → Stop → change plan*, ou activer un swap. |
