<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
  <#if section = "header">
  <#elseif section = "form">
    <main class="shell">
      <section class="card" aria-label="Ошибка входа">
        <div class="card-header">
          <h2>Не удалось продолжить вход</h2>
          <p>Сессия авторизации истекла или cookies заблокированы браузером.</p>
        </div>

        <#if message?has_content>
          <p class="error visible" role="alert">${kcSanitize(message.summary)?no_esc}</p>
        </#if>

        <div class="dev-hint" role="note">
          <strong>Что сделать</strong>
          <span>1. Разрешите cookies для этого сайта</span>
          <span>2. Откройте вход заново по ссылке ниже</span>
          <span>3. Используйте логин, не email: <code>hr.manager</code> / <code>admin</code></span>
        </div>

        <a class="btn btn-primary" href="/" target="_top">Начать вход заново</a>
      </section>
    </main>
  </#if>
</@layout.registrationLayout>
