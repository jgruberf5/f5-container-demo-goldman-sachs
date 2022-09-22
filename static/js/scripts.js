/*!
* Start Bootstrap - IBM Cloud Team ISC 2022 v7.0.5 (https://github.com/jgruberf5/ibmcloud_isc2022_web_app)
* Copyright 2013-2021 John Gruber
* Licensed under Apache2.0 (https://github.com/StartBootstrap/ibmcloudteam-isc-2022/blob/master/LICENSE)
*/

// jshint esversion:6

//
// Scripts
//
const demo1FailedImage = '/static/assets/img/service_disconnected_to_azure_cloud.svg';
const demo1SuccessImage = '/static/assets/img/service_connected_to_azure_cloud.svg';
const demo2FailedImage = '/static/assets/img/service_disconnected_to_service.svg';
const demo2SuccessImage = '/static/assets/img/service_connected_to_service.svg';
const demo3FailedImage = '/static/assets/img/service_disconnected_to_secured_web';
const demo3SuccessImage = '/static/assets/img/service_to_secured_web';
const demo4FailedImage = '/static/assets/img/office_disconnected_to_secured_web';
const demo4SuccessImage = '/static/assets/img/office_to_secured_web';

window.addEventListener('DOMContentLoaded', event => {

    // Navbar shrink function
    var navbarShrink = function () {
        const navbarCollapsible = document.body.querySelector('#mainNav');
        if (!navbarCollapsible) {
            return;
        }
        if (window.scrollY === 0) {
            navbarCollapsible.classList.remove('navbar-shrink');
        } else {
            navbarCollapsible.classList.add('navbar-shrink');
        }

    };

    // Shrink the navbar
    navbarShrink();

    // Shrink the navbar when page is scrolled
    document.addEventListener('scroll', navbarShrink);

    // Activate Bootstrap scrollspy on the main nav element
    const mainNav = document.body.querySelector('#mainNav');
    if (mainNav) {
        new bootstrap.ScrollSpy(document.body, {
            target: '#mainNav',
            offset: 74,
        });
    }

    // Collapse responsive navbar when toggler is visible
    const navbarToggler = document.body.querySelector('.navbar-toggler');
    const responsiveNavItems = [].slice.call(
        document.querySelectorAll('#navbarResponsive .nav-link')
    );
    responsiveNavItems.map(function (responsiveNavItem) {
        responsiveNavItem.addEventListener('click', () => {
            if (window.getComputedStyle(navbarToggler).display !== 'none') {
                navbarToggler.click();
            }
        });
    });

    // Activate SimpleLightbox plugin for portfolio items
    new SimpleLightbox({
        elements: '#portfolio a.portfolio-box'
    });

});

// reset demo screens on menu click
$(".nav-link").on("click", () => {
    initDemo1();
    initDemo2();
    initDemo3();
    initDemo4();
 });

// demo 1
const initDemo1 = () => {
    $("#spinner-demo1").hide();
    $("#demo1-description").show();
    $("#demo1-running").hide();
};

$("#start-demo1").on("click", () => {
    $("#demo1-description").hide();
    $("#demo1-running").show();
    $("#demo1-output").hide();
    $("#demo1-error").hide();
});
$('#run-demo1').on("click", () => {
    const protocol = 'cosmos';
    const fqdn = 'cloudmongo.default';
    const port = 80;
    const service = '';
    $("#demo1-error").html('').hide();
    $("#demo1-ouput").html('').hide();
    $("#demo1-diagram").attr("src",demo1FailedImage);
    $("#spinner-demo1").show();
    fetch('/resolv?fqdn=' + fqdn)
    .then((response) => {
        if (response.status == 404) {
            $("#demo1-error").html("service " + fqdn + " not found..").show();
            throw Error('Not found');
        } else {
            return response.json();
        }
    })
    .then((data) => {
        $('#demo1-output').html("service " + fqdn + " resolved to: " + data.message).show();
        const url = encodeURIComponent(protocol + '://' + fqdn + ':' + port + '/' + service + '?dbname=' + $('#cosmos-db-name').val() + '&dbkey=' + $('#cosmos-db-key').val());
        fetch('/dbconnect?url=' + url)
        .then((response) => {
            if (response.status > 399) {
                response.json().then( val => {
                    $("#demo1-error").html("service error:<br/><pre>" + val.message + "</pre>").show();
                    throw Error(val.message);
                });
            } else {
                $("#demo1-error").html("").hide();
                $("#demo1-diagram").attr("src",demo1SuccessImage);
                response.json().then ( val => {
                    const output = $("#demo1-output").html() + "<br/>Status: " + val.message;
                    $("#demo1-output").html(output).show();
                });
            }
        });
    }).catch( (error) => {

    }).finally( () => { $('#spinner-demo1').hide(); });
});


// demo 2
const initDemo2 = () => {
    $("#spinner-demo2").hide();
    $("#demo2-description").show();
    $("#demo2-running").hide();
};

$("#start-demo2").on("click", () => {
    $("#demo2-description").hide();
    $("#demo2-running").show();
    $("#demo2-output").hide();
    $("#demo2-error").hide();
});
$('#run-demo2').on("click", () => {
    const protocol = 'http';
    const fqdn = 'securedweb.default';
    service_name = '';
    $("#demo2-error").html('').hide();
    $("#demo2-ouput").html('').hide();
    $("#demo2-diagram").attr("src",demo2FailedImage);
    $("#spinner-demo2").show();
    fetch('/resolv?fqdn=' + fqdn)
    .then((response) => {
        if (response.status == 404) {
            $("#demo2-error").html("service " + fqdn + " not found..").show();
            throw Error('Not found');
        } else {
            return response.json();
        }
    })
    .then((data) => {
        $('#demo2-output').html("service " + fqdn + " resolved to: " + data.message).show();
        fetch('/webproxy?url='+ protocol + '://' + fqdn + '/' + service_name)
        .then((response) => {
            if (response.status > 399) {
                response.json().then( val => {
                    $("#demo2-error").html("service error:<br/><pre>" + val.message + "</pre>").show();
                    throw Error(val.message);
                });
            } else {
                $("#demo2-error").html("").hide();
                $("#demo2-diagram").attr("src",demo1SuccessImage);
                response.json().then ( val => {
                    const output = $("#demo2-output").html() + "<br/>Status: <div style='height: 230px; width: 640px; overflow-x: scroll; overflow-y: scroll;'>" + val.message + "</div>";
                    $("#demo2-output").html(output).show();
                });
            }
        });
    }).catch( (error) => {

    }).finally( () => { $('#spinner-demo2').hide(); });
});

// demo 3
const initDemo3 = () => {
    $("#spinner-demo3").hide();
    $("#demo3-description").show();
    $("#demo3-running").hide();
};

$("#start-demo3").on("click", () => {
    $("#demo3-description").hide();
    $("#demo3-running").show();
    $("#demo3-output").hide();
    $("#demo3-error").hide();
});
$('#run-demo3').on("click", () => {
    const protocol = 'http';
    const fqdn = 'webfrontend.default';
    service_name = '';
    $("#demo3-error").html('').hide();
    $("#demo3-ouput").html('').hide();
    $("#demo3-diagram").attr("src",demo3FailedImage);
    $("#spinner-demo3").show();
    fetch('/resolv?fqdn=' + fqdn)
    .then((response) => {
        if (response.status == 404) {
            $("#demo3-error").html("service " + fqdn + " not found..").show();
            throw Error('Not found');
        } else {
            return response.json();
        }
    })
    .then((data) => {
        $('#demo3-output').html("service " + fqdn + " resolved to: " + data.message).show();
        fetch('/webproxy?url=' + protocol + '://' + fqdn + '/' + service_name)
        .then((response) => {
            if (response.status > 399) {
                response.json().then( val => {
                    $("#demo3-error").html("service error:<br/><pre>" + val.message + "</pre>").show();
                    throw Error(val.message);
                });
            } else {
                $("#demo3-error").html("").hide();
                $("#demo3-diagram").attr("src",demo1SuccessImage);
                response.json().then ( val => {
                    const output = $("#demo3-output").html() + "<br/>Status: <div style='height: 230px; width: 640px; overflow-x: scroll; overflow-y: scroll;'>" + val.message + "</div>";
                    $("#demo3-output").html(output).show();
                });
            }
        });
    }).catch( (error) => {

    }).finally( () => { $('#spinner-demo3').hide(); });
});

// demo 4
const initDemo4 = () => {
    $("#spinner-demo4").hide();
    $("#demo4-description").show();
    $("#demo4-running").hide();
};
$("#start-demo4").on("click", () => {
    $("#demo4-description").hide();
    $("#demo4-running").show();
    $("#demo4-output").hide();
    $("#demo4-error").hide();
});
$('#run-demo4').on("click", () => {
    const protocol = 'https';
    const fqdn = 'gsapp.f5xc.edgesite.app';
    service_name = '';
    $("#demo4-error").html('').hide();
    $("#demo4-ouput").html('').hide();
    $("#demo4-diagram").attr("src",demo4FailedImage);
    $("#spinner-demo4").show();
    fetch('/resolv?fqdn=' + fqdn)
    .then((response) => {
        if (response.status == 404) {
            $("#demo4-error").html("service " + fqdn + " not found..").show();
            throw Error('Not found');
        } else {
            return response.json();
        }
    })
    .then((data) => {
        $('#demo4-output').html("service " + fqdn + " resolved to: " + data.message).show();
        fetch('/webproxy?url=' + protocol + '://' + fqdn + '/' + service_name)
        .then((response) => {
            if (response.status > 399) {
                response.json().then( val => {
                    $("#demo4-error").html("service error:<br/><pre>" + val.message + "</pre>").show();
                    throw Error(val.message);
                });
            } else {
                $("#demo4-error").html("").hide();
                $("#demo4-diagram").attr("src",demo1SuccessImage);
                response.json().then ( val => {
                    const output = $("#demo1-output").html() + "<br/>Status: <div style='height: 230px; width: 640px; overflow-x: scroll; overflow-y: scroll;'>" + val.message + "</div>";
                    $("#demo4-output").html(output).show();
                    window.open(protocol + '://' + fqdn + '/' + service_name, '_blank');
                });
            }
        });
    }).catch( (error) => {

    }).finally( () => { $('#spinner-demo4').hide(); });
});
