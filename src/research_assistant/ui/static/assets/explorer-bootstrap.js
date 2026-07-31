(() => {
  const originalFromEntries = Object.fromEntries;
  let armed = true;

  const patchedFromEntries = function patchedFromEntries(iterable) {
    const result = originalFromEntries.call(Object, iterable);
    if (
      armed &&
      Object.prototype.hasOwnProperty.call(result, "workspace-name") &&
      Object.prototype.hasOwnProperty.call(result, "file-tree") &&
      !Object.prototype.hasOwnProperty.call(result, "connection-status")
    ) {
      result["connection-status"] = document.getElementById("connection-status");
      armed = false;
      Object.fromEntries = originalFromEntries;
    }
    return result;
  };

  Object.fromEntries = patchedFromEntries;
  window.setTimeout(() => {
    if (Object.fromEntries === patchedFromEntries) {
      Object.fromEntries = originalFromEntries;
    }
  }, 10_000);
})();
