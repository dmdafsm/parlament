// Follow the system light/dark preference (no tracking, no storage beyond this tab).
(function () {
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
  function apply() { document.body.classList.toggle("dark", dark.matches); document.body.classList.toggle("light", !dark.matches); }
  if (dark) { apply(); dark.addEventListener("change", apply); }
  document.addEventListener("change", function (event) {
    var form = event.target.form;
    if (form && form.hasAttribute("data-autosubmit")) { form.requestSubmit(); }
  });
})();
