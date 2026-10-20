# Optional browser bridge

The bundled MV3 extension captures the full DOM of the currently clicked RoyaleAPI replay detail page. Permissions are `activeTab`, `scripting`, `nativeMessaging`; no Cookie/password API, browser-history, proxy-control or background-harvesting access. A full DOM may still contain account identifiers or page tokens: treat local HTML copies as sensitive and never upload/share them by default. Google login is completed by the user in their normal browser; embedded WebKit is independent.

After the user chooses Edge or Chrome and approves native-messaging registration, run:

```sh
python3 scripts/deploy.py register-bridge --target /absolute/deployment-directory --browser edge --confirm-browser-registration
```

This registers only the selected browser's user-level host manifest. It refuses to replace a different existing registration. The extension has a public manifest key so its expected ID remains `dbjcdkkejbaccfpnicafnkjaehkjhkjf` across installations; there is no signing private key in this skill.

Ask the user to open `edge://extensions` or `chrome://extensions`, confirm developer-mode/unpacked-extension installation, choose `<deployment>/official-web-replay/browser-extension`, then verify that ID. Do not edit browser Preferences/Secure Preferences or launch with security-disabling flags.

Usage: log in normally → open a full RoyaleAPI replay detail page → click extension → current DOM is saved to the private local queue → normal full-validation player starts. No network listener is created. Browser login/CAPTCHA/extension approval remain user actions. A queued job or successful protocol test is not proof of a rendered battle.
