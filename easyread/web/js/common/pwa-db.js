/* Shared, dependency-free IndexedDB helpers; snapshots never contain credentials. */
(function (root) {
  "use strict";
  let opening;
  function open() {
    if (!opening) opening = new Promise((resolve, reject) => {
      const request = indexedDB.open("easyread-offline", 1);
      request.onupgradeneeded = () => {
        for (const name of ["meta", "papers", "lists"]) request.result.createObjectStore(name);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => { opening = null; reject(request.error); };
    });
    return opening;
  }
  async function run(store, mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, mode), request = action(tx.objectStore(store));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error("Storage transaction failed"));
    });
  }
  root.EasyReadOfflineDB = {
    get: (store, key) => run(store, "readonly", s => s.get(key)),
    put: (store, key, value) => run(store, "readwrite", s => s.put(value, key)),
    del: (store, key) => run(store, "readwrite", s => s.delete(key)),
    all: store => run(store, "readonly", s => s.getAll()),
  };
})(globalThis);
