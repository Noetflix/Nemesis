# CI/CD de Némésis (GitHub Actions → VM Oracle)

Pipeline en deux temps, calqué sur le flux dev → prod :

```
PR vers main ───────────▶  CI (ci.yml)      : ruff format --check + ruff check + import
                                                └─ doit passer avant de merger

merge/push sur main ────▶  Deploy (deploy.yml)
                             1. verify   : re-vérifie le code (lint + import)
                             2. deploy   : ⏸ ATTEND ton approbation (environnement
                                            « production »), puis SSH vers la VM :
                                            git reset --hard origin/main
                                            uv sync
                                            sudo systemctl restart nemesis
```

`main` = **prod**. Tes branches + PR = **dev**. Rien ne part en prod sans ton clic
« Approve ».

> Prérequis : la VM Oracle est en place et le bot tourne déjà en service systemd
> (voir `deploy/DEPLOY.md`). Le CI/CD ne fait que rejouer les étapes de la section
> « Mettre à jour le bot » de façon automatisée et sécurisée.

---

## 1. Clé SSH dédiée au déploiement

Ne réutilise pas ta clé perso : génère une paire dédiée à GitHub Actions (révocable
indépendamment).

```bash
# Sur ton PC (ou n'importe où) — sans passphrase (Actions ne peut pas la saisir)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f nemesis_deploy -N ""
```

Ça produit `nemesis_deploy` (clé **privée**) et `nemesis_deploy.pub` (clé **publique**).

Autorise la clé publique sur la VM :

```bash
# Sur la VM (connecté en ubuntu)
echo "CONTENU_DE_nemesis_deploy.pub" >> ~/.ssh/authorized_keys
```

---

## 2. Sudo sans mot de passe pour le seul redémarrage du service

Actions n'a pas de terminal pour taper un mot de passe sudo. On autorise donc
`ubuntu` à redémarrer **uniquement** le service Némésis, rien d'autre :

```bash
# Sur la VM
echo 'ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nemesis, /usr/bin/systemctl is-active nemesis' \
  | sudo tee /etc/sudoers.d/nemesis-deploy
sudo chmod 440 /etc/sudoers.d/nemesis-deploy
```

> Vérifie le chemin de `systemctl` avec `which systemctl` (souvent
> `/usr/bin/systemctl` sur Ubuntu 24.04). Adapte la ligne sinon.

---

## 3. Secrets du dépôt GitHub

`Settings → Secrets and variables → Actions → New repository secret` :

| Secret | Valeur |
| --- | --- |
| `SSH_HOST` | IP publique de la VM Oracle |
| `SSH_USER` | `ubuntu` |
| `SSH_KEY` | Contenu **entier** de la clé privée `nemesis_deploy` (avec les lignes `-----BEGIN/END-----`) |

---

## 4. Environnement « production » (la validation manuelle)

`Settings → Environments → New environment` → nom exact : **`production`**.

- Coche **Required reviewers** et ajoute **toi-même**.
- (Optionnel) **Deployment branches** → *Selected branches* → `main`, pour interdire
  tout déploiement depuis une autre branche.

C'est ce qui met le job `deploy` en pause avec un bouton « Review deployments » :
tu cliques **Approve** quand tu veux vraiment passer en prod.

---

## 5. Premier déploiement

Une fois secrets + environnement en place :

1. Merge une PR (ou pousse) sur `main`.
2. Onglet **Actions** → run **Deploy** → le job `verify` passe, `deploy` affiche
   *Waiting*.
3. Clique **Review deployments** → **Approve and deploy**.
4. Le SSH s'exécute ; le run se termine sur `systemctl is-active nemesis` → `active`.

Tu peux aussi déclencher un déploiement à la demande :
**Actions → Deploy → Run workflow**.

---

## Dépannage

| Symptôme | Piste |
| --- | --- |
| `Permission denied (publickey)` | Clé publique absente de `~/.ssh/authorized_keys` sur la VM, ou `SSH_KEY` incomplète (copier la clé **privée** entière). |
| `sudo: a password is required` | Le fichier `/etc/sudoers.d/nemesis-deploy` manque ou le chemin de `systemctl` diffère. |
| `uv: not found` | Ajuster `~/.local/bin/uv` dans `deploy.yml` selon `which uv` sur la VM. |
| Le job `deploy` ne démarre jamais | Environnement `production` pas approuvé (bouton *Review deployments*). |
| `git reset` échoue (dépôt sale) | Un fichier suivi a été modifié sur la VM ; ne modifie jamais le code en prod (il est écrasé). |
