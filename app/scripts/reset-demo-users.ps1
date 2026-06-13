# Пересоздаёт демо-пользователей Keycloak и обновляет demo-данные в БД.
param(
    [string]$KeycloakUrl = "http://localhost:8080",
    [string]$WebUrl = "http://localhost:5173",
    [string]$Realm = "max-education",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "admin"
)

$ErrorActionPreference = "Stop"

$DemoUsers = @(
    @{
        username = "hr.manager"
        email = "hr.manager@company.ru"
        firstName = "Anna"
        lastName = "Ivanova"
        password = "hr123456"
        roles = @("hr_manager")
    },
    @{
        username = "teacher.demo"
        email = "teacher.demo@company.ru"
        firstName = "Petr"
        lastName = "Sidorov"
        password = "teacher123456"
        roles = @("teacher")
    },
    @{
        username = "admin"
        email = "admin@company.ru"
        firstName = "System"
        lastName = "Admin"
        password = "admin123456"
        roles = @("admin", "hr_manager")
    }
)

$ExtraDeleteUsernames = @("alvik")

function Get-AdminToken {
    $body = "grant_type=password&client_id=admin-cli&username=$AdminUser&password=$AdminPassword"
    $response = Invoke-RestMethod -Uri "$KeycloakUrl/realms/master/protocol/openid-connect/token" `
        -Method Post -ContentType "application/x-www-form-urlencoded" -Body $body
    return $response.access_token
}

function Invoke-KeycloakJson {
    param(
        [string]$Method,
        [string]$Uri,
        [string]$Token,
        [string]$Body
    )

    $headers = @{ Authorization = "Bearer $Token" }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $bytes = $utf8.GetBytes($Body)
    return Invoke-WebRequest -Uri $Uri -Method $Method -Headers $headers -Body $bytes `
        -ContentType "application/json; charset=utf-8" -UseBasicParsing
}

function Remove-UserByUsername {
    param([string]$Token, [string]$Username)
    $headers = @{ Authorization = "Bearer $Token" }
    $users = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/users?username=$Username&exact=true" -Headers $headers
    foreach ($user in $users) {
        Write-Host "  delete: $($user.username) ($($user.id))"
        Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/users/$($user.id)" -Method Delete -Headers $headers | Out-Null
    }
}

function New-DemoUser {
    param(
        [string]$Token,
        [hashtable]$UserSpec,
        [array]$RealmRoles
    )

    $payload = (@{
        username = $UserSpec.username
        email = $UserSpec.email
        firstName = $UserSpec.firstName
        lastName = $UserSpec.lastName
        enabled = $true
        emailVerified = $true
    } | ConvertTo-Json -Compress)

    $createResponse = Invoke-KeycloakJson -Method Post -Token $Token `
        -Uri "$KeycloakUrl/admin/realms/$Realm/users" -Body $payload
    if ($createResponse.StatusCode -ne 201) {
        throw "Не удалось создать $($UserSpec.username): HTTP $($createResponse.StatusCode)"
    }

    $userId = ($createResponse.Headers.Location -split "/")[-1]

    $passwordBody = (@{
        type = "password"
        value = $UserSpec.password
        temporary = $false
    } | ConvertTo-Json -Compress)
    Invoke-KeycloakJson -Method Put -Token $Token `
        -Uri "$KeycloakUrl/admin/realms/$Realm/users/$userId/reset-password" -Body $passwordBody | Out-Null

    $roleMappings = foreach ($roleName in $UserSpec.roles) {
        $role = $RealmRoles | Where-Object { $_.name -eq $roleName } | Select-Object -First 1
        if (-not $role) {
            throw "Роль не найдена: $roleName"
        }
        [PSCustomObject]@{
            id = $role.id
            name = $role.name
        }
    }

    $rolesBody = ConvertTo-Json -InputObject @($roleMappings) -Compress
    Invoke-KeycloakJson -Method Post -Token $Token `
        -Uri "$KeycloakUrl/admin/realms/$Realm/users/$userId/role-mappings/realm" -Body $rolesBody | Out-Null

    Write-Host "  create: $($UserSpec.username) / $($UserSpec.password) roles=$($UserSpec.roles -join ',')"
}

function Enable-DirectAccessGrant {
    param([string]$Token, [string]$ClientId)
    $headers = @{ Authorization = "Bearer $Token" }
    $clients = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients?clientId=$ClientId" -Headers $headers
    $client = $clients | Select-Object -First 1
    if (-not $client) {
        throw "Клиент не найден: $ClientId"
    }

    $client.directAccessGrantsEnabled = $true
    $client.standardFlowEnabled = $true
    $body = $client | ConvertTo-Json -Depth 20 -Compress
    Invoke-KeycloakJson -Method Put -Token $Token `
        -Uri "$KeycloakUrl/admin/realms/$Realm/clients/$($client.id)" -Body $body | Out-Null
    Write-Host "  client: $ClientId directAccessGrantsEnabled=true"
}

Write-Host "=== Keycloak: пересоздание демо-пользователей ==="
$token = Get-AdminToken
$headers = @{ Authorization = "Bearer $token" }
$realmRoles = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/roles" -Headers $headers

Write-Host "-> web clients"
Enable-DirectAccessGrant -Token $token -ClientId "hr-web"
Enable-DirectAccessGrant -Token $token -ClientId "teacher-web"

$deleteUsernames = ($DemoUsers | ForEach-Object { $_.username }) + $ExtraDeleteUsernames
foreach ($username in $deleteUsernames) {
    Write-Host "-> $username"
    Remove-UserByUsername -Token $token -Username $username
}

foreach ($spec in $DemoUsers) {
    New-DemoUser -Token $token -UserSpec $spec -RealmRoles $realmRoles
}

Write-Host ""
Write-Host "=== БД: seed-demo ==="
$seed = Invoke-RestMethod -Uri "$WebUrl/api/v1/db/seed-demo" -Method Post
Write-Host ($seed | ConvertTo-Json -Compress)

Write-Host ""
Write-Host "=== Проверка ==="
$users = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/users?max=100" -Headers $headers
foreach ($user in ($users | Sort-Object username)) {
    $roles = (Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/users/$($user.id)/role-mappings/realm" -Headers $headers).name
    Write-Host "$($user.username) | enabled=$($user.enabled) | roles=$($roles -join ',')"
}

Write-Host ""
Write-Host "Готово. Учётные записи:"
Write-Host "  HR:            hr.manager / hr123456        -> http://localhost:5173/"
Write-Host "  Преподаватель: teacher.demo / teacher123456 -> http://localhost:5173/"
Write-Host "  Админ:         admin / admin123456"
