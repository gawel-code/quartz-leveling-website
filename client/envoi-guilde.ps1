# Envoi automatique du fichier GuildExport.lua vers le site Quartz Forever.
# Premier lancement : demande la clé personnelle et cherche le fichier de l'addon ;
# tout est retenu ensuite dans %APPDATA%\QuartzForever (config.json, envoi.log).
# -Reconfigurer : redemande la clé et l'emplacement du fichier.
param([switch]$Reconfigurer)

$Serveur = if ($env:QUARTZ_SERVEUR) { $env:QUARTZ_SERVEUR } else { "https://quartz.gawel.be" }
$Dossier = Join-Path ($(if ($env:APPDATA) { $env:APPDATA } else { $HOME })) "QuartzForever"
$FichierConfig = Join-Path $Dossier "config.json"
$Journal = Join-Path $Dossier "envoi.log"
New-Item -ItemType Directory -Force -Path $Dossier | Out-Null

function Log($message) {
    $ligne = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $message"
    Write-Host $ligne
    Add-Content -Path $Journal -Value $ligne -Encoding UTF8
}

function Envoyer($cle, $contenu) {
    Invoke-RestMethod -Method Post -Uri "$Serveur/envoyer" -Headers @{ "X-Cle" = $cle } -TimeoutSec 30 `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($contenu)) -ContentType "text/plain; charset=utf-8"
}

function CodeHttp($erreur) {
    try { return [int]$erreur.Exception.Response.StatusCode } catch { return 0 }
}

# Une bonne clé avec un fichier vide renvoie 400, une mauvaise clé 403.
function TesterCle($cle) {
    try { Envoyer $cle "GuildExportDB = {}" | Out-Null; return $true }
    catch {
        $err = $_
        switch (CodeHttp $err) { 400 { return $true } 403 { return $false } default { throw $err } }
    }
}

function DemanderCle {
    while ($true) {
        $saisie = (Read-Host "Colle ta clé personnelle (reçue en message privé)").Trim()
        if (-not $saisie) { continue }
        try {
            if (TesterCle $saisie) { Log "Clé acceptée par le site."; return $saisie }
            Write-Host "Clé refusée par le site : copie uniquement la clé, sans ton pseudo ni le « : »."
        } catch {
            Write-Host "Site injoignable ($($_.Exception.Message)). Nouvel essai dans 10 secondes."
            Start-Sleep -Seconds 10
        }
    }
}

# Cherche GuildExport.lua dans les installations habituelles de WoW (le plus récent gagne).
function TrouverFichier {
    $racines = @("${env:ProgramFiles(x86)}\World of Warcraft", "$env:ProgramFiles\World of Warcraft")
    foreach ($lecteur in "C", "D", "E") {
        $racines += "${lecteur}:\World of Warcraft", "${lecteur}:\Games\World of Warcraft", "${lecteur}:\Jeux\World of Warcraft"
    }
    $racines | ForEach-Object {
        Get-ChildItem -Path "$_\_forever_\WTF\Account\*\SavedVariables\GuildExport.lua" -ErrorAction SilentlyContinue
    } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function DemanderFichier {
    $trouve = TrouverFichier
    if ($trouve) { Log "Fichier de l'addon trouvé : $($trouve.FullName)"; return $trouve.FullName }
    Write-Host "Fichier GuildExport.lua introuvable automatiquement (l'addon ne l'écrit qu'à la déconnexion ou au /reload)."
    while ($true) {
        $chemin = (Read-Host "Colle le chemin du fichier GuildExport.lua, ou du dossier SavedVariables").Trim().Trim('"')
        if (-not $chemin) { continue }
        if (Test-Path -LiteralPath $chemin -PathType Container) { $chemin = Join-Path $chemin "GuildExport.lua" }
        if (Test-Path -LiteralPath (Split-Path $chemin) -PathType Container) { Log "Fichier surveillé : $chemin"; return $chemin }
        Write-Host "Dossier introuvable : $(Split-Path $chemin)"
    }
}

function Sauver($config) { $config | ConvertTo-Json | Set-Content -Path $FichierConfig -Encoding UTF8 }

# ----- Configuration -----
$config = $null
if (-not $Reconfigurer -and (Test-Path $FichierConfig)) {
    try { $config = Get-Content $FichierConfig -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $config = $null }
}
if (-not $config) { $config = [pscustomobject]@{ cle = ""; fichier = "" } }
if (-not $config.cle) { $config.cle = DemanderCle; Sauver $config }
if (-not $config.fichier -or -not (Test-Path -LiteralPath (Split-Path $config.fichier) -PathType Container)) {
    $config.fichier = DemanderFichier; Sauver $config
}

# ----- Surveillance -----
Log "Envoi automatique actif vers $Serveur. Laisse cette fenêtre ouverte (tu peux la réduire)."
Log "Fichier surveillé : $($config.fichier)"
Write-Host "Journal : $Journal"
$derniereDate = $null
while ($true) {
    if (Test-Path -LiteralPath $config.fichier) {
        $date = (Get-Item -LiteralPath $config.fichier).LastWriteTime
        if ($date -ne $derniereDate) {
            try {
                $contenu = [System.IO.File]::ReadAllText($config.fichier, [System.Text.Encoding]::UTF8)
                $r = Envoyer $config.cle $contenu
                Log "Envoyé : $($r.personnages) personnages, $($r.nouveautes) mises à jour."
                $derniereDate = $date
            } catch {
                $err = $_
                switch (CodeHttp $err) {
                    403 {
                        Log "Clé refusée par le site (changée ou retirée)."
                        $config.cle = DemanderCle; Sauver $config
                    }
                    400 {
                        Log "Fichier vide ou invalide : connecte-toi en jeu avec l'addon, puis /reload."
                        $derniereDate = $date
                    }
                    default { Log "Échec de l'envoi ($($err.Exception.Message)), nouvel essai dans 30 secondes." }
                }
            }
        }
    }
    if ($env:QUARTZ_UNE_FOIS) { break }  # tests
    Start-Sleep -Seconds 30
}
