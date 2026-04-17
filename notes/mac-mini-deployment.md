# Mac mini Deployment

## Role split

- MacBook Pro = build console, git console, VS Code console
- Mac mini = LAIA Core target appliance

## Deployment model

The MacBook remains the source of truth.
The Mac mini receives the repo and runs the stack.

## 1. Prepare the Mac mini

Install:

- Docker Desktop
- Git
- VS Code or VS Code Server / Remote access

Optional but recommended:

- Enable SSH
- Set a stable hostname
- Keep the machine on Ethernet if possible

## 2. Get the repo onto the Mac mini

Option A: clone from git

```bash
git clone <your-repo-url> ~/LAIA-Core
cd ~/LAIA-Core