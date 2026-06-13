<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('password','password-confirm'); section>
  <#if section = "header">
  <#elseif section = "form">
    <main class="shell">
      <section class="card" aria-label="Смена пароля">
        <div class="card-header">
          <h2>Смена пароля</h2>
          <p>Установите новый пароль для вашей учётной записи</p>
        </div>

        <#if message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
          <p class="error visible" role="alert">${kcSanitize(message.summary)?no_esc}</p>
        </#if>

        <form id="kc-passwd-update-form" action="${url.loginAction}" method="post">
          <div class="field">
            <label for="password-new">Новый пароль</label>
            <input type="password" id="password-new" name="password-new" autofocus autocomplete="new-password"
                   aria-invalid="<#if messagesPerField.existsError('password','password-confirm')>true</#if>" />
            <#if messagesPerField.existsError('password')>
              <p class="error visible" role="alert">${kcSanitize(messagesPerField.get('password'))?no_esc}</p>
            </#if>
          </div>

          <div class="field">
            <label for="password-confirm">Подтверждение пароля</label>
            <input type="password" id="password-confirm" name="password-confirm" autocomplete="new-password"
                   aria-invalid="<#if messagesPerField.existsError('password','password-confirm')>true</#if>" />
            <#if messagesPerField.existsError('password-confirm')>
              <p class="error visible" role="alert">${kcSanitize(messagesPerField.get('password-confirm'))?no_esc}</p>
            </#if>
          </div>

          <button class="btn btn-primary" type="submit">Сохранить</button>

          <#if isAppInitiatedAction??>
            <div class="actions" style="margin-top: 12px;">
              <button class="back-link" type="submit" name="cancel-aia" value="true">Отмена</button>
            </div>
          </#if>
        </form>
      </section>
    </main>
  <#elseif section = "info">
  <#elseif section = "socialProviders">
  </#if>
</@layout.registrationLayout>
