document.addEventListener("DOMContentLoaded", () => {
  const Btnsearchbar = document.querySelector(".Searchbarbtn");
  const Searchbar = document.querySelector(".Searchbar");
  const Input = document.querySelector(".Searchbar input");

  Btnsearchbar.addEventListener("click", () => {
    Searchbar.classList.toggle("open"); // mở/đóng thanh tìm kiếm
    if (Searchbar.classList.contains("open")) {
      Input.focus(); // tự động focus vào ô nhập khi mở
    } else {
      Input.blur(); // bỏ focus khi đóng
    }
  });
});

const logreBox = document.querySelector(".logreg-box");

const loginLink = document.querySelector(".login-Link");

const registerLink = document.querySelector(".register-Link");

registerLink.addEventListener("click", () => {
  logreBox.classList.add("active");
});

loginLink.addEventListener("click", () => {
  logreBox.classList.remove("active");
});
