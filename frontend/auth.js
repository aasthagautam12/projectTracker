function saveUser(email, password){
  const users = JSON.parse(localStorage.getItem('users')||'{}');
  users[email] = { email, password };// demo only
  localStorage.setItem('users', JSON.stringify(users));
}
function checkUser(email, password){
  const users = JSON.parse(localStorage.getItem('users')||'{}');
  const u = users[email];
  return !!(u && u.password === password);
}
function setAuthed(email){
  localStorage.setItem('auth_user', email);
}
function requireAuth(){
  if(!localStorage.getItem('auth_user')){
    location.href = 'login.html';
  }
}

// signup
const sf = document.getElementById('signupForm');
if (sf){
  sf.addEventListener('submit', (e)=>{
    e.preventDefault();
    const email = document.getElementById('s_email').value.trim();
    const password = document.getElementById('s_password').value;
    saveUser(email, password);
    setAuthed(email);
    location.href = 'index.html';
  });
}

// login
const lf = document.getElementById('loginForm');
if (lf){
  lf.addEventListener('submit', (e)=>{
    e.preventDefault();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    if(checkUser(email, password)){
      setAuthed(email);
      location.href = 'index.html';
    } else {
      alert('Invalid credentials');
    }
  });
}