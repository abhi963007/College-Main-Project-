const body = document.querySelector("body");
const navbar = document.querySelector("nav");
const menuBtn = document.querySelector(".menu-btn");
const cancelBtn = document.querySelector(".cancel-btn");

menuBtn.onclick = () => {
  navbar.classList.add("show");
  menuBtn.classList.add("hide");
  body.classList.add("disabled");
};

cancelBtn.onclick = () => {
  body.classList.remove("disabled");
  navbar.classList.remove("show");
  menuBtn.classList.remove("hide");
};

// Sticky Navigation Menu
let lastScroll = 0;
window.addEventListener("scroll", () => {
    const currentScroll = window.pageYOffset;
    
    // Make navbar sticky when scrolling down
    if (currentScroll > 100) {
        navbar.classList.add("sticky");
        
        // Hide navbar when scrolling down, show when scrolling up
        if (currentScroll > lastScroll && !navbar.classList.contains("show")) {
            navbar.classList.add("hide");
        } else {
            navbar.classList.remove("hide");
        }
    } else {
        navbar.classList.remove("sticky");
        navbar.classList.remove("hide");
    }
    
    lastScroll = currentScroll;
});