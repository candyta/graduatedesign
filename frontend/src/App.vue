<template>
  <div id="app">
    <BNCTPlatform />
  </div>
</template>

<script>
import BNCTPlatform from './components/BNCTPlatform.vue'

export default {
  name: 'App',
  components: {
    BNCTPlatform
  }
}
</script>

<style>
#app {
  margin: 0;
  padding: 0;
}

body {
  margin: 0;
  padding: 0;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}
</style>
