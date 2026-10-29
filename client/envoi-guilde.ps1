# ===== À PERSONNALISER =====
$Serveur = "https://quartz.gawel.be"
$Cle     = "COLLE-TA-CLE-ICI"
$Fichier = "C:\Program Files (x86)\World of Warcraft\_forever_\WTF\Account\TON_COMPTE\SavedVariables\GuildExport.lua"
# ===========================

Write-Host "Envoi automatique des données de guilde actif. Laisse cette fenêtre ouverte (tu peux la réduire)."
$derniereDate = $null
while ($true) {
    if (Test-Path $Fichier) {
        $date = (Get-Item $Fichier).LastWriteTime
        if ($date -ne $derniereDate) {
            try {
                $contenu = [System.IO.File]::ReadAllText($Fichier, [System.Text.Encoding]::UTF8)
                $r = Invoke-RestMethod -Method Post -Uri "$Serveur/envoyer" `
                     -Headers @{ "X-Cle" = $Cle } `
                     -Body ([System.Text.Encoding]::UTF8.GetBytes($contenu)) `
                     -ContentType "text/plain; charset=utf-8"
                Write-Host "$(Get-Date -Format 'HH:mm') - Envoyé : $($r.personnages) personnages, $($r.nouveautes) mises à jour."
                $derniereDate = $date
            } catch {
                Write-Host "$(Get-Date -Format 'HH:mm') - Échec de l'envoi, nouvel essai dans 30 secondes."
            }
        }
    }
    Start-Sleep -Seconds 30
}
