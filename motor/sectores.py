"""Clasificación sectorial a partir del código SIC que cada empresa declara a la SEC."""


def sector(sic):
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return "Otros"
    r = lambda a, b: a <= s <= b
    if s in (1311, 1381, 1382, 1389, 2911, 2990, 4922, 4923, 5171, 5172) or r(1200, 1299) or r(2900, 2999) or r(4610, 4619):
        return "Energía"
    if r(2833, 2836) or r(3840, 3851) or r(8000, 8099) or s in (5122, 5047, 6324, 8731, 3826, 3827):
        return "Salud"
    if r(7370, 7379) or r(3570, 3579) or r(3660, 3679) or s in (3559, 3576, 3577, 3812, 3823, 3825, 3829, 3861, 5045, 3690):
        return "Tecnología"
    if r(6500, 6599) or s == 6798:
        return "Inmobiliario"
    if r(6000, 6799):
        return "Financiero"
    if r(4900, 4999):
        return "Servicios públicos"
    if r(4800, 4899) or r(2700, 2799) or r(7800, 7841) or s in (7310, 7311):
        return "Comunicación"
    if r(100, 999) or r(2000, 2199) or r(2840, 2844) or r(5140, 5149) or r(5400, 5499) or s in (5912, 5331, 5399):
        return "Consumo básico"
    if s != 3021 and (r(1000, 1499) or r(2400, 2499) or r(2600, 2699) or r(2800, 2899) or r(3000, 3099) or r(3200, 3399)):
        return "Materiales"
    if (r(2200, 2399) or r(2500, 2599) or r(3100, 3199) or s == 3021 or r(3630, 3659) or s in (3711, 3713, 3714, 3715, 3716, 3751, 1531)
            or r(3900, 3999) or r(5200, 5999) or r(7000, 7099) or r(7900, 7999) or s in (5090, 5094, 7200, 8200)):
        return "Consumo discrecional"
    if (r(1500, 1799) or r(3400, 3599) or r(3600, 3699) or r(3700, 3799) or r(3800, 3899) or r(4000, 4799)
            or r(5000, 5199) or r(7300, 7399) or r(8700, 8799) or r(7500, 7699)):
        return "Industrial"
    return "Otros"
