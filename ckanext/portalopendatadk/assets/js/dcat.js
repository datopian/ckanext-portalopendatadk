$(document).ready(function () {
  var dcat_fields = ["field-notes", "field-title", "field-organizations"];

  function updateDcatFields() {
    console.log($("#field-data_directory"));
    if ($("#field-data_directory").is(":checked")) {
      for (var i = 0; i < dcat_fields.length; i++) {
        var field = $("#" + dcat_fields[i]);
        field.attr("required", "required");
        var label = $('label[for="' + dcat_fields[i] + '"]');
        if (label.children("span.control-required").length === 0) {
          label.prepend(
            '<span title="Feltet er påkrævet" class="control-required">* </span>'
          );
        }
      }
    } else {
      for (var i = 0; i < dcat_fields.length; i++) {
        var field = $("#" + dcat_fields[i]);
        field.removeAttr("required");
        var label = $('label[for="' + dcat_fields[i] + '"]');
        label.find("span.control-required").remove();
      }
    }
  }

  $("#field-data_directory").change(updateDcatFields);

  if ($("#field-data_directory").is(":checked")) {
    updateDcatFields();
  }
});

$('form').on('submit', function(e) {
  const formData = new FormData(this);
  console.log([...formData.entries()]);
});
