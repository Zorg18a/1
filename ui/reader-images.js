// An image can fail independently of the chapter manifest; never infer its cause.
export function setupReaderImage({ doc, image, number, src }) {
  const panel = doc.createElement('div');
  panel.className = 'reader-image-error';
  panel.hidden = true;
  const message = doc.createElement('p');
  message.setAttribute('role', 'status');
  const retry = doc.createElement('button');
  retry.type = 'button';
  retry.textContent = `Повторить загрузку страницы ${number}`;
  panel.append(message, retry);
  let retrying = false, attempt = 0;
  image.addEventListener('error', () => {
    retrying = false;
    message.textContent = `Не удалось загрузить страницу ${number}. Проверьте файл и подключение к MediaHub.`;
    panel.hidden = false;
  });
  image.addEventListener('load', () => {
    const focusImage = retrying && doc.activeElement === retry;
    retrying = false;
    panel.hidden = true;
    message.textContent = '';
    if (focusImage) {
      image.tabIndex = -1;
      image.focus({ preventScroll: true });
    }
  });
  retry.addEventListener('click', () => {
    retrying = true;
    message.textContent = `Повторная загрузка страницы ${number}…`;
    // Avoid reusing a cached failed response for the same local page.
    image.src = `${src}?retry=${Date.now()}-${++attempt}`;
  });
  return panel;
}
