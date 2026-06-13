<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled??; section>
  <#if section = "header">
  <#elseif section = "form">
    <main class="shell">
      <section class="card" aria-label="Вход через Keycloak">
        <div class="card-header">
          <h2>Вход в систему</h2>
          <p>Введите логин и пароль — система сама откроет нужный портал</p>
        </div>

        <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
          <p class="error visible" role="alert">${kcSanitize(message.summary)?no_esc}</p>
        </#if>

        <#if messagesPerField.existsError('username','password')>
          <p class="error visible" role="alert">${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}</p>
        </#if>

        <div class="dev-hint" role="note">
          <strong>Тестовые учётные записи</strong>
          <span>HR: <code>hr.manager</code> / <code>hr123456</code></span>
          <span>Преподаватель: <code>teacher.demo</code> / <code>teacher123456</code></span>
          <span>Админ: <code>admin</code> / <code>admin123456</code></span>
        </div>

        <form id="kc-form-login" action="${url.loginAction}" method="post">
          <div class="field">
            <label for="username">Имя пользователя</label>
            <input tabindex="1" id="username" name="username" value="${(login.username!'')}" type="text"
                   autofocus autocomplete="username"
                   aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                   placeholder="hr.manager или teacher.demo" />
          </div>

          <div class="field">
            <label for="password">Пароль</label>
            <input tabindex="2" id="password" name="password" type="password" autocomplete="current-password"
                   aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                   placeholder="••••••••" />
          </div>

          <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if> />

          <button tabindex="4" class="btn btn-primary" name="login" id="kc-login" type="submit">Войти</button>
        </form>

        <div class="divider">или</div>

        <a class="btn btn-max" href="/max" target="_top">Войти через MAX</a>
      </section>
    </main>
  <#elseif section = "info">
  <#elseif section = "socialProviders">
  </#if>
</@layout.registrationLayout>
